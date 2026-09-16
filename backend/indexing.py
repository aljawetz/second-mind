"""Chunking + indexing — implementation-plan.md Step 6.

Wires ingestion.py's extraction output into LlamaIndex nodes carrying
citation-anchor metadata (rag-pipeline.md §2): a page or slide is a node,
not an arbitrary token window — SentenceSplitter only kicks in for prose
long enough to actually need it. Indexed into a LanceDB table via
LlamaIndex's official integration (rag-pipeline.md §4).

Path convention matches data-model.md §1 (~/.ssb/<id>/index.lancedb/course_<code>/)
but this module takes db_path as a parameter — callers decide where that
actually points (a real student directory, or a scratch dir for tests).
"""

from pathlib import Path
from typing import Any

from lancedb.expr import col, lit
from llama_index.core import StorageContext, VectorStoreIndex, set_global_tokenizer
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from tokenizers import Tokenizer

from embeddings import MODEL_DIR, OnnxBgeEmbedding

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


def pages_to_nodes(pages: list[dict], source: str, canvas_item_id: str) -> list[TextNode]:
    """One node per page, split further only if the page's prose actually
    exceeds the target chunk size — most extracted pages don't."""
    nodes = []
    for page in pages:
        text = page["text"]
        if not text.strip():
            continue
        for chunk in _splitter.split_text(text):
            node = TextNode(text=chunk, metadata={"source": source, "page": page["page"]})
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
        node = TextNode(text=text, metadata={"source": source, "slide": slide["slide"]})
        nodes.append(_with_ref_doc(node, canvas_item_id))
    return nodes


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
    return VectorStoreIndex(
        nodes, storage_context=storage_context, embed_model=OnnxBgeEmbedding(), transformations=[_splitter]
    )


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
