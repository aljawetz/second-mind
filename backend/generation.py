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

import providers
import reranker as reranker_module

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
# Sprint 8 raised this from 1 to 10: the FTS hits now go through rank
# fusion with the vector hits (below), so a weak tail match only makes the
# final top 5 if nothing ranks above it. Still no score threshold.
FTS_TOP_K = 10

# Sprint 8: both searches fetch more candidates than they return, then the
# two lists are merged with reciprocal rank fusion (RRF). RRF only uses each
# result's rank inside its own list, so the BM25 and cosine scales never get
# compared. RRF_K = 60 is the usual value from the original RRF paper.
VECTOR_CANDIDATES = 20
RRF_K = 60

# Sprint 8 PR 3: rank fusion picks a larger pool (RERANK_CANDIDATES), a
# local cross-encoder (reranker.py) scores each one against the question,
# and only the best similarity_top_k at or above RERANK_MIN_SCORE are kept.
# The reranker score is a 0 to 1 sigmoid, comparable across courses, so it
# is the one place a cutoff applies to keyword hits too. A question with
# nothing above the cutoff returns no results, which is the honest answer
# for something the course never covered. See RERANK_MIN_SCORE's tuning
# note in docs and the PR: chosen on the sprint7 eval set itself.
RERANK_CANDIDATES = 20
RERANK_MIN_SCORE = 0.01

_DEFAULT = object()


def reciprocal_rank_fusion(ranked_lists: list[list[NodeWithScore]], k: int = RRF_K, top_n: int = 5) -> list[NodeWithScore]:
    """Merge ranked lists into one. Each node gets the sum of 1 / (k + rank)
    over the lists it is in (rank starts at 1). A node in two lists is kept
    once, as its first copy, so its original score is not changed. Ties
    keep the order the nodes were first seen in."""
    fused: dict[str, float] = {}
    first: dict[str, NodeWithScore] = {}
    for ranked in ranked_lists:
        seen_here: set[str] = set()
        for rank, node_with_score in enumerate(ranked, start=1):
            node_id = node_with_score.node.node_id
            if node_id in seen_here:
                continue
            seen_here.add(node_id)
            fused[node_id] = fused.get(node_id, 0.0) + 1.0 / (k + rank)
            first.setdefault(node_id, node_with_score)
    order = sorted(fused, key=lambda node_id: -fused[node_id])
    return [first[node_id] for node_id in order[:top_n]]

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
    re-filters either kind against a scale it was never computed on.

    Sprint 8: the two lists are now merged by rank with reciprocal rank
    fusion (see reciprocal_rank_fusion) and cut to similarity_top_k. Each
    node keeps its own original score; only the order comes from fusion.

    Sprint 8 PR 3: when a reranker is available, fusion keeps
    rerank_candidates results instead, the reranker scores each one, and
    the top similarity_top_k with a rerank score of at least
    rerank_min_score are returned, each with its rerank score (0 to 1) as
    its score. reranker=None, or a missing model, means fusion only."""

    def __init__(
        self,
        index,
        similarity_top_k: int = 5,
        similarity_cutoff: float = SIMILARITY_CUTOFF,
        reranker=_DEFAULT,
        rerank_candidates: int = RERANK_CANDIDATES,
        rerank_min_score: float = RERANK_MIN_SCORE,
    ):
        self._index = index
        self._similarity_top_k = similarity_top_k
        self._similarity_cutoff = similarity_cutoff
        self._reranker = reranker_module.load_reranker() if reranker is _DEFAULT else reranker
        self._rerank_candidates = rerank_candidates
        self._rerank_min_score = rerank_min_score
        super().__init__()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        vector_nodes = self._index.as_retriever(similarity_top_k=VECTOR_CANDIDATES).retrieve(query_bundle)
        vector_nodes = SimilarityPostprocessor(similarity_cutoff=self._similarity_cutoff).postprocess_nodes(vector_nodes)

        table = self._index.vector_store.table
        fts_df = table.search(query_bundle.query_str, query_type="fts").limit(FTS_TOP_K).to_pandas()
        fts_nodes = [
            NodeWithScore(node=metadata_dict_to_node(row["metadata"]), score=float(row["_score"]))
            for _, row in fts_df.iterrows()
        ]

        if self._reranker is None:
            return reciprocal_rank_fusion([vector_nodes, fts_nodes], k=RRF_K, top_n=self._similarity_top_k)
        pool = reciprocal_rank_fusion([vector_nodes, fts_nodes], k=RRF_K, top_n=self._rerank_candidates)
        return rerank(self._reranker, query_bundle.query_str, pool, self._similarity_top_k, self._rerank_min_score)


def rerank(reranker, query: str, nodes: list[NodeWithScore], top_n: int, min_score: float) -> list[NodeWithScore]:
    """Order nodes by reranker score, drop those under min_score, keep
    top_n. Ties keep the incoming (fusion) order. If the reranker fails at
    query time, fall back to the incoming order cut to top_n."""
    if not nodes:
        return []
    try:
        scores = reranker.score(query, [n.node.get_content() for n in nodes])
    except Exception:
        reranker_module.logger.exception("Reranker failed; using rank fusion order")
        return nodes[:top_n]
    order = sorted(range(len(nodes)), key=lambda i: -scores[i])
    kept = [NodeWithScore(node=nodes[i].node, score=float(scores[i])) for i in order if scores[i] >= min_score]
    return kept[:top_n]


def build_query_engine(index, streaming: bool = True) -> CitationQueryEngine:
    llm = providers.llama_llm()
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
        source_rel = node.relationships.get(NodeRelationship.SOURCE)
        citations.append(citation_for(node.metadata, source_rel.node_id if source_rel else ""))
    return citations


def location(metadata: dict) -> str:
    """Where in its document a chunk sits: "p.3", "slide 4", "14:22", or ""."""
    # Every node now always carries all of page/slide/timestamp
    # (indexing.py's _metadata, Step 12) — only some populated per
    # node — so these must check the value, not just key presence.
    if metadata.get("page") is not None:
        return f"p.{metadata['page']}"
    if metadata.get("slide") is not None:
        return f"slide {metadata['slide']}"
    if metadata.get("timestamp") is not None:
        return metadata["timestamp"]
    return ""


def citation_for(metadata: dict, item_id: str) -> dict:
    """One chunk's citation: chat answers (above) and study artifacts (study.py)."""
    source = metadata.get("source") or ""
    where = location(metadata)
    return {
        "source_type": metadata.get("item_type") or "file",
        "label": f"{source} · {where}" if where else source,
        "item_id": item_id,
    }
