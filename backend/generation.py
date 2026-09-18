"""Generation — implementation-plan.md Step 8.

Wires CitationQueryEngine + SimilarityPostprocessor + a pluggable LLM
client around a real index. The system prompt encodes design spec §7's
grounding rules: answer-first by default, Socratic mode as an opt-in
toggle, cite every factual claim, never blend in open-domain knowledge.
"""

import keyring
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.prompts import PromptTemplate
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.core.schema import NodeRelationship, NodeWithScore
from llama_index.llms.openai import OpenAI

CREDENTIAL_SERVICE = "com.ssb.app"

# Shown when grounded=False (design spec §7: "if indexed material does not
# support an answer, SSB says so rather than falling back to open-domain
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

# config.json (data-model.md §3) doesn't exist as real code yet — nothing
# in this codebase reads/writes it (Step 2 only built Keychain
# credentials). Hardcoded here deliberately rather than building config
# file I/O this step doesn't otherwise need.
DEFAULT_MODEL = "gpt-4o-mini"

ANSWER_FIRST_TEMPLATE = PromptTemplate(
    "You are SSB, a study assistant. Answer the question directly and "
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

SOCRATIC_TEMPLATE = PromptTemplate(
    "You are SSB, a study assistant in Socratic mode. Instead of "
    "answering directly, ask one or two guiding questions that lead the "
    "student toward the answer, using only the numbered sources below. "
    "Reference sources by number, e.g. [1], when pointing to relevant "
    "material. If the sources don't contain enough information to help, "
    "say so explicitly instead of guessing.\n"
    "------\n"
    "{context_str}\n"
    "------\n"
    "Query: {query_str}\n"
    "Guiding questions: "
)


def _get_llm_key() -> str:
    key = keyring.get_password(CREDENTIAL_SERVICE, "openai-key")
    if not key:
        raise RuntimeError("no LLM API key stored — onboarding hasn't completed")
    return key


def build_query_engine(index, socratic: bool = False, streaming: bool = True) -> CitationQueryEngine:
    llm = OpenAI(model=DEFAULT_MODEL, api_key=_get_llm_key())
    template = SOCRATIC_TEMPLATE if socratic else ANSWER_FIRST_TEMPLATE
    return CitationQueryEngine.from_args(
        index,
        llm=llm,
        node_postprocessors=[SimilarityPostprocessor(similarity_cutoff=SIMILARITY_CUTOFF)],
        citation_qa_template=template,
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
