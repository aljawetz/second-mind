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

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
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
_splitter = SentenceSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    tokenizer=lambda text: _bge_tokenizer.encode(text).tokens,
)


def pages_to_nodes(pages: list[dict], source: str) -> list[TextNode]:
    """One node per page, split further only if the page's prose actually
    exceeds the target chunk size — most extracted pages don't."""
    nodes = []
    for page in pages:
        text = page["text"]
        if not text.strip():
            continue
        for chunk in _splitter.split_text(text):
            nodes.append(TextNode(text=chunk, metadata={"source": source, "page": page["page"]}))
    return nodes


def slides_to_nodes(slides: list[dict], source: str) -> list[TextNode]:
    """One node per slide, not split — a slide is a citation unit
    (rag-pipeline.md §2), not something to fragment across chunks."""
    nodes = []
    for slide in slides:
        text = slide["text"]
        if not text.strip():
            continue
        nodes.append(TextNode(text=text, metadata={"source": source, "slide": slide["slide"]}))
    return nodes


def build_index(nodes: list[TextNode], db_path: Path, table_name: str) -> VectorStoreIndex:
    vector_store = LanceDBVectorStore(uri=str(db_path), table_name=table_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex(nodes, storage_context=storage_context, embed_model=OnnxBgeEmbedding())
