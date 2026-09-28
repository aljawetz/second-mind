"""Course chat behind POST /courses/{id}/ask — option D from
docs/evaluations/2026-09-23-ask-modes/report.md.

The model sees the whole chat and searches the course with a tool, as many
times as it needs, instead of the old one-shot retrieve-then-answer. It may
add its own general knowledge, but only under a fixed label, and course facts
must come from search results with citations. Evaluated against the old
pipeline on 67 questions across three courses: it's the only option that
handled follow-up questions ("explain the second one") and was honest about
what the course doesn't cover.

Four fixes from that report and its follow-up checks live in code, not in
the prompt, because the prompt alone didn't hold:
- The student's own question is always searched first. The model tends to
  search with short keywords ("final exam date"), which score lower than the
  full sentence and fell under the similarity cutoff on smaller courses.
- In a follow-up, the model must search in its own words before answering.
- Citations are checked and renumbered here. The model's [n] numbers span
  every search it made; only numbers that match a real search result survive,
  renumbered 1..k in the order the answer uses them.
- The general-knowledge label is a fixed string the frontend splits on, so
  the app can mark that part of the answer visibly.

With agent memory on (memory=, docs/superpowers/specs/2026-09-25-agent-memory-design.md
§5.5), the model also sees what the student told it in earlier chats: a
profile in the system prompt, the question recalled once up front (the same
reasoning as the first search), and recall_memory / forget_memory tools.
Memory is never course material: its [M1] labels are stripped from the
answer here, and forget_memory only accepts labels shown in this turn.
"""

import json
import re
from typing import Callable, Iterator

from llama_index.core.schema import NodeWithScore

import generation
from llm import LLMProvider, ToolCall, TurnEnd
from memory.compress import summary_block
from memory.recall import Hit, format_hits

GENERAL_KNOWLEDGE_LABEL = "General knowledge (not from your course materials):"

SYSTEM_PROMPT = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- The student's question has already been searched once for you. Search again with your own wording \
whenever that result doesn't clearly answer it, and always for follow-up questions. You can search more \
than once. The only exception is when the student only asks you to reformat or shorten your previous answer.
- Facts about this course (dates, grading, weights, policies, deadlines, assignments, staff, what was said \
in class) must come only from search results. Copy numbers and dates exactly as the source states them. If \
the source text looks garbled or incomplete, say so instead of guessing. If you can't find it, say you \
couldn't find it in the course materials.
- Only cite a source for a claim that source actually states. Never add a citation to general knowledge.
- Cite with the source number in square brackets only, like [2] or [1][3]. Never write file names, page \
numbers or the word "source" as a citation.
- Your answer has up to two parts:
  1. What the course materials say, with citations. Leave this part out if they say nothing relevant, and \
say so in one sentence.
  2. Only if it helps (the course doesn't cover it, or the student asked for a simpler explanation or an \
extra example): a part that starts with the line "{label}". \
Everything you add from your own knowledge goes here, and nothing without a citation goes above it.
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_course",
        "description": (
            "Search this student's course materials (lecture slides, readings, syllabus, "
            "assignment descriptions, Canvas pages, class recording transcripts). Returns "
            "numbered sources. Use a clear, specific query; you can call it more than once."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look for."}},
            "required": ["query"],
        },
    },
}

MEMORY_RULES = """

You also remember what this student told you in earlier conversations.
- What you already know about them is listed at the end of these instructions, when there is anything. Use \
it to fit your answer to them (their team, their project, how they like examples) without being asked.
- Search it with the recall_memory tool. The student's question has already been recalled once for you \
when anything matched. Set include_history to true for questions about what changed or what something was before.
- Memories are the student's own words, not course material. Never cite them with [n], and never write their \
[M1] labels in your answer; mention them naturally ("You mentioned you're on team 4"). Course facts still come \
only from search_course, even if the student remembers them differently.
- If the student asks you to forget something, find it with recall_memory unless it's already shown, then call \
forget_memory with its label."""

RECALL_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": (
            "Search what this student told you in earlier conversations: their team, project, preferences, "
            "and progress on assignments. Returns labeled memories like [M1]. Not course material."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "include_history": {
                    "type": "boolean",
                    "description": "Also return memories that were later replaced or withdrawn, with the dates they were true.",
                },
            },
            "required": ["query"],
        },
    },
}

FORGET_TOOL = {
    "type": "function",
    "function": {
        "name": "forget_memory",
        "description": (
            "Permanently delete memories the student asked you to forget, by the labels they were shown with "
            "in this turn (like M1)."
        ),
        "parameters": {
            "type": "object",
            "properties": {"labels": {"type": "array", "items": {"type": "string"}}},
            "required": ["labels"],
        },
    },
}

MAX_TOOL_ROUNDS = 4
# Whole chunks, not a preview: indexing.py's chunks top out around 3,800
# characters, and answers often sit past the first 1,500 (the Requirements
# course's final exam date is at character ~2,470 of its page). An earlier
# 1,500 cap hid them — found in the held-out evaluation.
SNIPPET_CHARS = 4000
HISTORY_TURNS = 6
HISTORY_ANSWER_CHARS = 1500
NO_RESULTS = "No matching course material found for this search."

# One or more source numbers in brackets: [3], [1, 4], [1][3] is two matches.
# The optional space before it goes too when a citation is dropped entirely.
_CITATION = re.compile(r"(\s?)\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")
# Memory labels, [M1] or [M1, M2]: always dropped, with the space before.
_MEMORY_LABEL = re.compile(r"\s?\[\s*M\d+(?:\s*,\s*M?\d+)*\s*\]")
# Longest unclosed "[..." held back while streaming, in case it's a citation
# split across chunks. Longer than any real citation, short enough that a
# stray "[" in prose doesn't stall the stream.
_MAX_PENDING = 16


def parse_history(raw) -> list[dict]:
    """Validates /ask's optional history: a list of {question, answer} strings."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("history must be a list")
    turns = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str) or not isinstance(item.get("answer"), str):
            raise ValueError("each history item needs string 'question' and 'answer'")
        turns.append({"question": item["question"], "answer": item["answer"]})
    return turns


def _history_messages(history: list[dict]) -> list[dict]:
    # Earlier answers' [n] numbers pointed at earlier searches. Left in, the
    # model would read them as numbers of this answer's sources.
    messages = []
    for turn in history[-HISTORY_TURNS:]:
        answer = _CITATION.sub("", turn["answer"])[:HISTORY_ANSWER_CHARS]
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": answer})
    return messages


class CitationRenumberer:
    """Rewrites streamed text's [n] markers as they pass through.

    Numbers that match a search result become 1..k in order of first use;
    numbers that don't (the model inventing [9] with five sources) are
    dropped. `order` holds the original source numbers in display order.
    Memory labels ([M1]) are dropped too: memory is never a citation."""

    def __init__(self, is_valid: Callable[[int], bool]):
        self._is_valid = is_valid
        self._display: dict[int, int] = {}
        self.order: list[int] = []
        self._pending = ""

    def _renumber(self, match: re.Match) -> str:
        out = []
        for part in match.group(2).split(","):
            n = int(part)
            if not self._is_valid(n):
                continue
            if n not in self._display:
                self.order.append(n)
                self._display[n] = len(self.order)
            out.append(f"[{self._display[n]}]")
        return match.group(1) + "".join(out) if out else ""

    def feed(self, text: str) -> str:
        text = self._pending + text
        self._pending = ""
        cut = text.rfind("[")
        if cut != -1 and "]" not in text[cut:] and len(text) - cut <= _MAX_PENDING:
            # The space before the "[" waits with it, so it can go too if
            # the bracket turns out to be a dropped citation or a memory label.
            while cut > 0 and text[cut - 1] == " ":
                cut -= 1
            text, self._pending = text[:cut], text[cut:]
        return self._rewrite(text)

    def flush(self) -> str:
        text, self._pending = self._pending, ""
        return self._rewrite(text)

    def _rewrite(self, text: str) -> str:
        return _MEMORY_LABEL.sub("", _CITATION.sub(self._renumber, text))


def make_search(index, similarity_cutoff: float = generation.SIMILARITY_CUTOFF) -> Callable[[str], list[NodeWithScore]]:
    """index=None (course not indexed yet) searches nothing, so the model says
    it couldn't find anything instead of the request failing."""
    if index is None:
        return lambda query: []
    retriever = generation.HybridRetriever(index, similarity_cutoff=similarity_cutoff)
    return lambda query: retriever.retrieve(query)


def answer(
    question: str,
    history: list[dict],
    course_name: str,
    search: Callable[[str], list[NodeWithScore]],
    provider: LLMProvider,
    memory=None,
    summary: str = "",
) -> Iterator[dict]:
    """Yields /ask's stream events: {"delta"} text pieces, then one
    {"citations", "grounded"}, then {"done": True}. With `memory` (a
    memory.MemoryService), the final event also has "memories_used": the
    memories recalled this turn and not forgotten, [{id, text}], so the app
    can show what the answer drew on. The profile isn't listed: it's there
    on every question. `summary` is the conversation's running summary when
    `history` is only its last few turns (memory.compress).

    Nothing is yielded until the model starts writing its answer, so errors
    from searching or the first model calls surface before the caller has
    sent any response bytes."""
    sources: list[NodeWithScore] = []
    number_of: dict[str, int] = {}
    shown: dict[str, str] = {}  # "M1" -> memory id, what forget_memory accepts
    used: dict[str, str] = {}  # memory id -> text, in the order first shown
    forgotten: set[str] = set()

    def run_search(query: str) -> str:
        parts = []
        for node_with_score in search(query):
            node_id = node_with_score.node.node_id
            if node_id not in number_of:
                sources.append(node_with_score)
                number_of[node_id] = len(sources)
            label = generation.build_citations([node_with_score])[0]["label"]
            content = node_with_score.node.get_content()[:SNIPPET_CHARS]
            parts.append(f"[{number_of[node_id]}] {label}\n{content}")
        return "\n\n".join(parts) if parts else NO_RESULTS

    def show(hits: list[Hit]) -> str:
        first = len(shown) + 1
        for label, hit in enumerate(hits, start=first):
            shown[f"M{label}"] = hit.memory.id
            used.setdefault(hit.memory.id, hit.memory.text)
        return format_hits(hits, first_label=first)

    def run_forget(labels) -> str:
        wanted = [str(label).strip("[] ").upper() for label in labels] if isinstance(labels, list) else []
        unknown = [label for label in wanted if label not in shown]
        ids = [i for i in dict.fromkeys(shown[label] for label in wanted if label in shown) if i not in forgotten]
        parts = []
        if ids and memory.forget(ids):
            forgotten.update(ids)
            parts.append(
                "Forgotten, deleted from memory: " + "; ".join(used[i] for i in ids) + " If the student said it in a "
                "saved chat, it's still in that chat; deleting that chat removes it completely."
            )
        if unknown:
            parts.append(
                f"No memory labeled {', '.join(unknown)} was shown in this turn. Find it with recall_memory, then "
                "use the label it's shown with."
            )
        return " ".join(parts) or "Nothing to forget."

    def run_tool(call: ToolCall) -> str:
        query = call.arguments.get("query")
        has_query = isinstance(query, str) and query.strip()
        if call.name == "search_course" and has_query:
            return run_search(query)
        if memory is not None and call.name == "recall_memory" and has_query:
            return show(memory.recall(query, include_history=call.arguments.get("include_history") is True))
        if memory is not None and call.name == "forget_memory":
            return run_forget(call.arguments.get("labels"))
        return "Unknown tool or empty query."

    prompt = SYSTEM_PROMPT.format(course_name=course_name, label=GENERAL_KNOWLEDGE_LABEL)
    tools = [SEARCH_TOOL]
    if memory is not None:
        tools = [SEARCH_TOOL, RECALL_TOOL, FORGET_TOOL]
        prompt += MEMORY_RULES
        profile = memory.profile_block()
        if profile:
            prompt += "\n\n" + profile
    if summary:
        prompt += "\n\n" + summary_block(summary)
    messages = [{"role": "system", "content": prompt}, *_history_messages(history), {"role": "user", "content": question}]
    # The first search is made here, in the model's name, so it always
    # happens and always uses the student's exact words.
    messages.append({"role": "assistant", "content": None, "tool_calls": [_call("search-0", "search_course", {"query": question})]})
    messages.append({"role": "tool", "tool_call_id": "search-0", "content": run_search(question)})
    # Memory too, for the same reason: left to the model, it would often not
    # look. Only added when something matched, so an unrelated question
    # costs nothing extra.
    if memory is not None:
        hits = memory.recall(question)
        if hits:
            messages.append({"role": "assistant", "content": None, "tool_calls": [_call("recall-0", "recall_memory", {"query": question})]})
            messages.append({"role": "tool", "tool_call_id": "recall-0", "content": show(hits)})

    renumberer = CitationRenumberer(lambda n: 1 <= n <= len(sources))
    for round_num in range(MAX_TOOL_ROUNDS + 1):
        round_tools = tools if round_num < MAX_TOOL_ROUNDS else None
        # In a follow-up ("And the final?") the student's exact words rarely
        # find anything useful, and the prompt alone didn't stop the model
        # from answering "couldn't find it" off that one weak search (seen
        # live). So its first move in a follow-up must be a search in its own
        # words, written with the chat in view.
        require_tool = round_num == 0 and bool(history)
        round_text = ""
        end = TurnEnd()
        for item in provider.stream_chat(messages, round_tools, require_tool=require_tool):
            if isinstance(item, TurnEnd):
                end = item
                continue
            round_text += item
            out = renumberer.feed(item)
            if out:
                yield {"delta": out}
        if not end.tool_calls:
            break
        messages.append(
            {
                "role": "assistant",
                "content": round_text or None,
                "tool_calls": [_call(c.id, c.name, c.arguments) for c in end.tool_calls],
            }
        )
        for call in end.tool_calls:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": run_tool(call)})

    tail = renumberer.flush()
    if tail:
        yield {"delta": tail}
    citations = generation.build_citations([sources[n - 1] for n in renumberer.order])
    final = {"citations": citations, "grounded": bool(citations)}
    if memory is not None:
        final["memories_used"] = [{"id": i, "text": text} for i, text in used.items() if i not in forgotten]
    yield final
    yield {"done": True}


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
