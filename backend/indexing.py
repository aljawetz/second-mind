"""Chunking + indexing — implementation-plan.md Step 6.

Wires ingestion.py's extraction output into LlamaIndex nodes carrying
citation-anchor metadata (rag-pipeline.md §2): a page or slide is a node,
not an arbitrary token window — SentenceSplitter only kicks in for prose
long enough to actually need it. Indexed into a LanceDB table via
LlamaIndex's official integration (rag-pipeline.md §4).

Path convention matches data-model.md §1 (~/.secondmind/index.lancedb/course_<code>/)
but this module takes db_path as a parameter — callers decide where that
actually points (the real ~/.secondmind/, or a scratch dir for tests).
"""

from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from lancedb.expr import col, lit
from llama_index.core import StorageContext, VectorStoreIndex, set_global_tokenizer
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from tokenizers import Tokenizer

from embeddings import EMBEDDING_DIM, MODEL_DIR, OnnxBgeEmbedding

CHUNK_SIZE = 700  # tokens, rag-pipeline.md §2's ~500-800 target
CHUNK_OVERLAP = 100  # ~15% of 700

# SentenceSplitter's default tokenizer is tiktoken (GPT-style) — two real
# problems found by actually running this frozen: (1) it doesn't bundle
# cleanly under PyInstaller (its encoding data isn't discoverable in a
# frozen build), and (2) counting tokens with a different tokenizer than
# the one the embedding model actually uses means a "700-token" chunk by
# tiktoken's count could exceed BGE's real 512-token limit (which is what
# originally crashed onnxruntime — embeddings.py's truncation stays as a
# safety net, but this is the correct fix at the source).
_bge_tokenizer = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
_tokenize = lambda text: _bge_tokenizer.encode(text).tokens

# Real finding (Step 9, only caught by actually running the frozen binary,
# not `uv run python3`): tiktoken isn't just SentenceSplitter's default —
# llama_index's internal get_tokenizer() is called from multiple places
# (PromptHelper's TokenCounter, used by every query engine, is a second,
# separate one found here) and ALL of them fall back to the same
# module-global `llama_index.core.global_tokenizer` when it's unset. Fixing
# only the splitter above left this second path crashing with the exact
# same "Unknown encoding cl100k_base" in the frozen build. Setting it once,
# globally, covers every current and future call site instead of chasing
# them one at a time.
set_global_tokenizer(_tokenize)

_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, tokenizer=_tokenize)


def _with_ref_doc(node: TextNode, canvas_item_id: str) -> TextNode:
    """Sets the node's ref_doc_id to canvas_item_id (data-model.md §4) — what
    both the LanceDB integration's doc_id column and delete_ref_doc rely on."""
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=canvas_item_id)
    return node


def _metadata(source: str, item_type: str, *, page=None, slide=None, timestamp=None) -> dict:
    """Every node across every node-creation function carries the same set
    of metadata keys, only some populated per node — required, not just
    tidy: LanceDB infers a table's column schema from whatever the first
    batch of nodes happens to contain, and a plain columnar insert can't
    add a new column later. A table built from Canvas pages alone (only
    ever seeing "page") rejected a later insert of transcript nodes
    ("timestamp") with "field 'timestamp' does not exist in table schema"
    — a real, previously-latent bug Step 12 surfaced, the first time this
    project ever inserted a second, differently-shaped node type into an
    existing table rather than building a table fresh in one batch."""
    return {"source": source, "item_type": item_type, "page": page, "slide": slide, "timestamp": timestamp}


def pages_to_nodes(pages: list[dict], source: str, canvas_item_id: str, item_type: str = "file") -> list[TextNode]:
    """One node per page, split further only if the page's prose actually
    exceeds the target chunk size — most extracted pages don't.

    item_type defaults to "file" for the original PDF-page caller
    (generation.py's citation formatting reads this back as source_type);
    course_sync.py passes item_type="page" for Canvas wiki pages, which
    aren't paginated at all, so their nodes carry page=None."""
    nodes = []
    for page in pages:
        text = page["text"]
        if not text.strip():
            continue
        for chunk in _splitter.split_text(text):
            node = TextNode(text=chunk, metadata=_metadata(source, item_type, page=page["page"]))
            nodes.append(_with_ref_doc(node, canvas_item_id))
    return nodes


def slides_to_nodes(slides: list[dict], source: str, canvas_item_id: str) -> list[TextNode]:
    """One node per slide, not split — a slide is a citation unit
    (rag-pipeline.md §2), not something to fragment across chunks."""
    nodes = []
    for slide in slides:
        text = slide["text"]
        if not text.strip():
            continue
        node = TextNode(text=text, metadata=_metadata(source, "file", slide=slide["slide"]))
        nodes.append(_with_ref_doc(node, canvas_item_id))
    return nodes


def _format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def transcript_to_nodes(segments: list[dict], source: str, session_id: str) -> list[TextNode]:
    """One node per ~2000-char group of consecutive faster-whisper segments
    (split further only if that group's text still exceeds the target chunk
    size), labeled by real timestamp rather than a page/slide number —
    matches overview.md's own citation example ("Lecture 6 · 14:22").
    Step 12 (design spec §9.3): transcript is indexed, notes are indexed
    separately (notes_to_nodes) — the AI note-enhancement step is
    transcript-only by product decision, but both stay searchable."""
    nodes = []
    buffer: list[str] = []
    buffer_start: float | None = None
    buffer_len = 0
    for seg in segments:
        if buffer_start is None:
            buffer_start = seg["start"]
        buffer.append(seg["text"])
        buffer_len += len(seg["text"])
        if buffer_len >= CHUNK_SIZE * 4:  # ~4 chars/token, rough gate before splitting further
            nodes += _flush_transcript_buffer(buffer, buffer_start, source, session_id)
            buffer, buffer_start, buffer_len = [], None, 0
    if buffer:
        nodes += _flush_transcript_buffer(buffer, buffer_start, source, session_id)
    return nodes


def _flush_transcript_buffer(buffer: list[str], start: float, source: str, session_id: str) -> list[TextNode]:
    text = " ".join(buffer).strip()
    if not text:
        return []
    nodes = []
    for chunk in _splitter.split_text(text):
        node = TextNode(text=chunk, metadata=_metadata(source, "transcript", timestamp=_format_timestamp(start)))
        nodes.append(_with_ref_doc(node, session_id))
    return nodes


def notes_to_nodes(notes_text: str, source: str, session_id: str) -> list[TextNode]:
    """The student's own rough in-class notes — indexed separately from the
    transcript, never fed into the AI note-enhancement step (that reads the
    transcript alone, by explicit product decision), but still searchable
    via Q&A like everything else the student captures."""
    if not notes_text.strip():
        return []
    nodes = []
    for chunk in _splitter.split_text(notes_text):
        node = TextNode(text=chunk, metadata=_metadata(source, "notes"))
        nodes.append(_with_ref_doc(node, session_id))
    return nodes


# Every course table's layout, stated up front instead of inferred. LanceDB
# otherwise infers column types from the first batch written, and a column
# that's None in every node of that batch becomes type null for good — so
# whichever material reached a course first decided what it could ever
# hold. Real data: a course whose first write was a lecture transcript
# (page=None) rejected every later PDF with "cannot cast field 'page' from
# Int64 to Null"; a PDF-first course rejected transcripts and pptx slides.
# The metadata fields are _metadata()'s keys plus the ones llama-index's
# node_to_metadata_dict adds, in the order it writes them.
_METADATA_TYPE = pa.struct(
    [
        ("source", pa.string()),
        ("item_type", pa.string()),
        ("page", pa.int64()),
        ("slide", pa.int64()),
        ("timestamp", pa.string()),
        ("_node_content", pa.string()),
        ("_node_type", pa.string()),
        ("document_id", pa.string()),
        ("doc_id", pa.string()),
        ("ref_doc_id", pa.string()),
    ]
)
TABLE_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("doc_id", pa.string()),
        ("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ("text", pa.string()),
        ("metadata", _METADATA_TYPE),
    ]
)



class _PatchedLanceDBVectorStore(LanceDBVectorStore):
    """llama-index-vector-stores-lancedb 0.6.0's delete(), delete_nodes(),
    and get_nodes() all build SQL predicates by string-concatenating raw
    values inside double quotes (e.g. `doc_id = "x"`), which LanceDB's
    DataFusion-based SQL dialect parses as an identifier reference, not a
    string literal — delete_ref_doc() fails for every input, not just
    ours. Confirmed directly against a raw LanceDB table before assuming
    it was our bug, not theirs, and confirmed still present on their
    `main` branch, not just the release (implementation-plan.md Step 7).
    Only delete() is overridden here — we don't call delete_nodes() or
    get_nodes() ourselves (yet).

    Fixed with LanceDB's own type-safe expression API (`col`/`lit`)
    instead of hand-escaping a SQL string — no string interpolation left
    to get wrong at all, not just correctly-quoted. Remove this override
    once upstream fixes it."""

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        self.table.delete(col(self.doc_id_key) == lit(ref_doc_id))

    def add(self, nodes, **add_kwargs: Any) -> list[str]:
        # The base class creates a missing table from the first batch's
        # inferred types; creating it empty with TABLE_SCHEMA first turns
        # that into a plain append against the right layout.
        if self._table is None and nodes:
            self._table = self._connection.create_table(self._table_name, schema=TABLE_SCHEMA, mode=self.mode)
        return super().add(nodes, **add_kwargs)


def build_index(nodes: list[TextNode], db_path: Path, table_name: str) -> VectorStoreIndex:
    vector_store = _PatchedLanceDBVectorStore(uri=str(db_path), table_name=table_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    # transformations must be explicit here, not left to fall back to
    # Settings.transformations' default: that default is a SentenceSplitter
    # built with tiktoken, and just constructing it (even on nodes that are
    # already pre-chunked and never actually re-split) crashed the frozen
    # PyInstaller build with "Unknown encoding cl100k_base" — the same
    # tiktoken-doesn't-bundle-cleanly problem the module docstring already
    # notes for chunking, just a second, previously-undiscovered code path
    # into the same default (implementation-plan.md Step 9 — only surfaced
    # by actually running the frozen binary, not `uv run python3`).
    index = VectorStoreIndex(
        nodes, storage_context=storage_context, embed_model=OnnxBgeEmbedding(), transformations=[_splitter]
    )
    ensure_fts_index(vector_store.table)
    return index


def load_index(db_path: Path, table_name: str) -> VectorStoreIndex:
    """Opens a previously-built table for querying, without re-adding nodes
    (main.py's /ask handler — the index was already populated by a sync,
    not by this request). transformations=[_splitter] for the same reason
    as build_index: avoids ever touching Settings' tiktoken-based default,
    even though no transformation actually runs against an empty node list."""
    vector_store = _PatchedLanceDBVectorStore(uri=str(db_path), table_name=table_name)
    return VectorStoreIndex.from_vector_store(
        vector_store, embed_model=OnnxBgeEmbedding(), transformations=[_splitter]
    )


def index_exists(db_path: Path, table_name: str) -> bool:
    if not db_path.exists():
        return False
    return table_name in lancedb.connect(str(db_path)).table_names()


def drop_table(db_path: Path, table_name: str) -> None:
    """Course DELETE (Step 13) — the whole table, not specific rows
    (delete_ref_doc_nodes is for one session; this is for the course
    itself, e.g. no longer selected and never coming back)."""
    if index_exists(db_path, table_name):
        lancedb.connect(str(db_path)).drop_table(table_name)


def ensure_fts_index(table) -> None:
    """Idempotent — LanceDB persists the FTS index on the table itself, so
    this only actually rebuilds when it's missing, not on every call.
    Real (harmless) deprecation warning: LanceDB's replacement API for this
    (`create_index(config=FTS())`) doesn't accept a column name the way the
    docs suggest — confirmed by trying it directly, not assumed — so this
    stays on the documented-deprecated-but-working call instead of chasing
    an unclear replacement signature. HybridRetriever (generation.py) is
    Step 12's real reason this exists: BM25 full-text search for exact
    name/keyword lookups vector search alone is weak at."""
    if any(getattr(i, "index_type", None) == "FTS" for i in table.list_indices()):
        return
    table.create_fts_index("text", replace=True)


def add_nodes(nodes: list[TextNode], db_path: Path, table_name: str) -> None:
    """Session capture's entry point (Step 12) — a course may have no index
    yet at all (a session recorded before any Canvas sync), so this can't
    assume load_index's table already exists the way /ask and /explain do."""
    if index_exists(db_path, table_name):
        index = load_index(db_path, table_name)
        index.insert_nodes(nodes)
        ensure_fts_index(index.vector_store.table)
    else:
        build_index(nodes, db_path, table_name)


def delete_ref_doc_nodes(db_path: Path, table_name: str, ref_doc_id: str) -> None:
    """Deleting a session (Step 12) — the first real caller of the delete()
    override _PatchedLanceDBVectorStore exists for for since Step 7 (that
    was built and verified against the raw table directly, but never
    exercised through an actual app feature until now)."""
    if not index_exists(db_path, table_name):
        return
    _PatchedLanceDBVectorStore(uri=str(db_path), table_name=table_name).delete(ref_doc_id)
