"""Generation — implementation-plan.md Step 8.

Wires CitationQueryEngine + SimilarityPostprocessor + a pluggable LLM
client around a real index. The system prompt encodes design spec §7's
grounding rules: answer-first, cite every factual claim, never blend in
open-domain knowledge.
"""

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.prompts import PromptTemplate
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.schema import NodeRelationship, NodeWithScore, QueryBundle
from llama_index.core.vector_stores.utils import metadata_dict_to_node
from llama_index.llms.openai import OpenAI

import config

CREDENTIAL_SERVICE = "com.secondmind.app"

# Shown when grounded=False (design spec §7: "if indexed material does not
# support an answer, Second Mind says so rather than falling back to open-domain
# knowledge") — covers both "nothing indexed yet" and "nothing relevant
# retrieved", which look identical from the student's side.
NOT_COVERED_MESSAGE = (
    "I couldn't find anything about that in your indexed course materials. "
    "Try rephrasing, or check whether it's covered in a file that hasn't been synced yet."
)

# Calibrated against real retrieval scores, not guessed: on-topic queries
# against real indexed content scored 0.6555-0.7524, deliberately
# off-topic queries scored 0.3077-0.3967 — a clean gap, no overlap.
# 0.5 sits with real margin on both sides, biased slightly toward the
# conservative end (reject a borderline match rather than risk an
# unsupported context reaching the LLM), per design spec §7's "grounding
# is non-negotiable." 4 on-topic + 3 off-topic queries against one real
# course — a real data point, not an exhaustive sweep; worth revisiting
# once more courses are indexed at scale, same caveat as the density
# heuristic's own calibration.
SIMILARITY_CUTOFF = 0.5

# No fixed magnitude cutoff for the FTS side (unlike SIMILARITY_CUTOFF
# above) — real finding (implementation-plan.md Step 12): BM25 magnitude
# depends on corpus statistics (term/document frequency), not a fixed 0-1
# scale like cosine similarity, so a threshold calibrated on one course's
# data doesn't transfer to another (confirmed: the same off-topic control
# query scored ~0 on one real course's corpus and ~4 on a different real
# course's — an order of magnitude apart, same query). Relative rank
# *within* one query's own FTS results is still meaningful even though
# absolute magnitude isn't comparable across corpora, so this takes only
# the single best FTS match (FTS_TOP_K) rather than thresholding score —
# minimizing exposure to weak tail matches. This doesn't eliminate false
# positives from real-but-incidental term overlap (a query sharing one
# real word with unrelated content — confirmed: "recipe" in a query
# matched real course slides citing the book "JUnit Recipes"), but
# CitationQueryEngine's own synthesis step is a real second line of
# defense — verified it still correctly declined to answer even with that
# weak match included, rather than fabricating an answer from it.
FTS_TOP_K = 1

# config.json (data-model.md §3) doesn't exist as real code yet — nothing
# in this codebase reads/writes it (Step 2 only built Keychain
# credentials). Hardcoded here deliberately rather than building config
# file I/O this step doesn't otherwise need.
DEFAULT_MODEL = "gpt-4o-mini"

ANSWER_FIRST_TEMPLATE = PromptTemplate(
    "You are Second Mind, a study assistant. Answer the question directly and "
    "concisely using only the numbered sources below. Cite every "
    "factual claim with its source number, e.g. [1]. If the sources "
    "don't contain enough information to answer, say so explicitly "
    "instead of guessing or using knowledge from outside the sources.\n"
    "------\n"
    "{context_str}\n"
    "------\n"
    "Query: {query_str}\n"
    "Answer: "
)


def _get_llm_key() -> str:
    key = config.get_credential("openai-key")
    if not key:
        raise RuntimeError("no LLM API key stored — onboarding hasn't completed")
    return key


class HybridRetriever(BaseRetriever):
    """Combines vector search (semantic — good for concepts) with LanceDB's
    native BM25 full-text search (exact keyword/name matching — what
    vector search is inherently weak at, since a proper noun doesn't have
    strong semantic "neighbors" the way a concept does). Built by hand,
    not via llama-index-vector-stores-lancedb's own query_type="hybrid":
    that path's score comes back as a fake rank-position number
    (`_to_llama_similarities`'s `np.linspace` fallback, confirmed by
    testing a real off-topic control query and finding the top result
    always scored 1.0 regardless of actual relevance) — unusable for a
    grounding threshold, so this keeps the two retrieval paths, and their
    non-comparable scores, deliberately separate instead of trying to
    fuse them into one number.

    Filtering happens here, inside the retriever, not via a
    node_postprocessor on the query engine — vector nodes are filtered
    against SIMILARITY_CUTOFF (cosine similarity, a real, portable
    threshold); FTS nodes have no threshold at all (see FTS_TOP_K) since
    BM25 magnitude isn't portable across corpora — only the single
    best-ranked FTS match is taken, and combined with the vector nodes
    only after both are independently decided, so nothing downstream
    re-filters either kind against a scale it was never computed on."""

    def __init__(self, index, similarity_top_k: int = 5, similarity_cutoff: float = SIMILARITY_CUTOFF):
        self._index = index
        self._similarity_top_k = similarity_top_k
        self._similarity_cutoff = similarity_cutoff
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        vector_nodes = self._index.as_retriever(similarity_top_k=self._similarity_top_k).retrieve(query_bundle)
        vector_nodes = SimilarityPostprocessor(similarity_cutoff=self._similarity_cutoff).postprocess_nodes(vector_nodes)
        seen_ids = {n.node.node_id for n in vector_nodes}

        table = self._index.vector_store.table
        fts_df = table.search(query_bundle.query_str, query_type="fts").limit(FTS_TOP_K).to_pandas()
        fts_nodes = []
        for _, row in fts_df.iterrows():
            node = metadata_dict_to_node(row["metadata"])
            if node.node_id in seen_ids:
                continue
            fts_nodes.append(NodeWithScore(node=node, score=float(row["_score"])))
            seen_ids.add(node.node_id)

        return vector_nodes + fts_nodes


def build_query_engine(index, streaming: bool = True) -> CitationQueryEngine:
    llm = OpenAI(model=DEFAULT_MODEL, api_key=_get_llm_key())
    return CitationQueryEngine.from_args(
        index,
        llm=llm,
        retriever=HybridRetriever(index),
        citation_qa_template=ANSWER_FIRST_TEMPLATE,
        streaming=streaming,
    )


def build_citations(source_nodes: list[NodeWithScore]) -> list[dict]:
    """Maps CitationQueryEngine's source_nodes to overview.md §2's citation
    shape. Verified against a real index (implementation-plan.md Step 9)
    that a node's metadata and SOURCE relationship both survive the round
    trip through LanceDB retrieval and CitationQueryEngine's own node
    splitting (it model_dump/model_validate-copies the full node).

    source_type reads indexing.py's own item_type metadata (added Step 12)
    rather than assuming "file" — "transcript"/"notes" are real, reachable
    values now that session capture indexes those node kinds too. "page"
    (Canvas wiki pages) is still unreached — nothing ingests those yet."""
    citations = []
    for node_with_score in source_nodes:
        node = node_with_score.node
        source = node.metadata.get("source", "")
        # Every node now always carries all of page/slide/timestamp
        # (indexing.py's _metadata, Step 12) — only some populated per
        # node — so these must check the value, not just key presence.
        if node.metadata.get("page") is not None:
            label = f"{source} · p.{node.metadata['page']}"
        elif node.metadata.get("slide") is not None:
            label = f"{source} · slide {node.metadata['slide']}"
        elif node.metadata.get("timestamp") is not None:
            label = f"{source} · {node.metadata['timestamp']}"
        else:
            label = source
        source_rel = node.relationships.get(NodeRelationship.SOURCE)
        item_id = source_rel.node_id if source_rel else ""
        source_type = node.metadata.get("item_type", "file")
        citations.append({"source_type": source_type, "label": label, "item_id": item_id})
    return citations
