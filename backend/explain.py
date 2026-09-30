"""Assignment explainer — implementation-plan.md Step 10, design spec §7.1.

Two independent pieces, deliberately built differently:

"What's being asked" (build_breakdown) is pure reading comprehension of the
assignment's own prompt text — no course retrieval, no citations. Grounded
in the assignment itself, not course content.

"Where to start" (build_pointers) is retrieval against the course's own
index, same mechanism as /ask's citations — but with NO LLM synthesis step
at all. This is a deliberate response to a real tested finding (design spec
§7.1): connecting a course concept to a *specific numbered task* in
generated prose ("this task needs a state flag — see Lecture 6...") reads
as implementation guidance even with zero code in it. A bare citation label
(the same "<source> · p.N" format /ask already uses) structurally can't do
that, because nothing is generated — it's a mechanical retrieval result,
not authored text. overview.md's own documented /explain contract already
reflects this: pointers are {label, item_id}, with no free-text field for
guidance to leak into.
"""

import re
from html.parser import HTMLParser

from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.prompts import PromptTemplate

import generation
import providers

BREAKDOWN_TEMPLATE = PromptTemplate(
    "You are Second Mind, a study assistant. Break the following assignment prompt "
    "into its actual sub-requirements, in plain, concise language — this is "
    "reading comprehension of the prompt's own structure, not advice on how "
    "to complete it. Do not suggest implementation approaches, do not name "
    "specific algorithms, data structures, or design patterns to use, and "
    "do not draft any part of a solution. One sub-requirement per line, no "
    "numbering or bullets.\n"
    "------\n"
    "Assignment: {name}\n"
    "{description}\n"
    "------\n"
    "Sub-requirements:\n"
)

_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div", "pre", "tr"}
_CODE_SPAN_RE = re.compile(r"<code>(.*?)</code>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class _TextExtractor(HTMLParser):
    """Just enough HTML-to-text for Canvas's rich-text assignment
    descriptions (paragraphs, lists, headings, code spans) — stdlib only,
    no new dependency for what's otherwise fairly simple markup."""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    lines = [line.strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def extract_code_identifiers(html: str) -> set[str]:
    """Real class/method/interface names the assignment prompt names
    explicitly via <code> tags — used only as a regression-test signal
    (implementation-plan.md Step 10): build_pointers should never be
    capable of naming these, since referencing them by name is exactly the
    "implementation guidance wearing an explanation costume" design spec
    §7.1 warns about. (build_breakdown is expected and allowed to restate
    them — it's summarizing the prompt's own structure.)"""
    idents = set()
    for m in _CODE_SPAN_RE.finditer(html):
        inner = _TAG_RE.sub("", m.group(1)).strip().rstrip(".,:;()")
        if _IDENTIFIER_RE.match(inner):
            idents.add(inner)
    return idents


def build_breakdown(name: str, description_text: str) -> list[str]:
    llm = providers.llama_llm()
    prompt = BREAKDOWN_TEMPLATE.format(name=name, description=description_text)
    response = llm.complete(prompt)
    lines = [line.strip(" \t-•") for line in str(response).splitlines()]
    return [line for line in lines if line]


POINTER_COUNT = 5


def build_pointers(index, name: str, description_text: str) -> list[dict]:
    # Assignments are indexed too (course_sync.py), and this query *is* an
    # assignment's own text, so its indexed copy would always rank first —
    # a pointer back to the prompt the student is already reading. Pointers
    # are for course material, so assignment items are dropped; retrieving
    # extra first keeps POINTER_COUNT real candidates after the filter.
    retriever = index.as_retriever(similarity_top_k=POINTER_COUNT * 3)
    nodes = retriever.retrieve(f"{name}\n\n{description_text}")
    nodes = [n for n in nodes if n.node.metadata.get("item_type") != "assignment"][:POINTER_COUNT]
    nodes = SimilarityPostprocessor(similarity_cutoff=generation.SIMILARITY_CUTOFF).postprocess_nodes(nodes)
    citations = generation.build_citations(nodes)
    # source_type carried through so the frontend can click-through a
    # pointer the same way it does a /ask citation (external Canvas link
    # vs. in-app session navigation) instead of only handling one of the
    # two places citations appear.
    return [{"label": c["label"], "item_id": c["item_id"], "source_type": c["source_type"]} for c in citations]
