"""Compare three ways of answering chat questions — see
docs/evaluations/2026-09-23-ask-modes/report.md for the write-up.

  A  today's /ask: always search, answer only from what the search returns,
     each question on its own (no chat history).
  B  search as a tool: the model sees the whole chat, decides when and what
     to search, answers only from course material.
  C  same as B, but the model may add its own general knowledge when the
     course doesn't cover something, labeled as such.
  D  C with stricter rules, written after reading the first run's C answers:
     always search, cite a source only for what it actually says, keep all
     general knowledge under the label, copy course numbers exactly.
  E  the shipped /ask code (chat.answer): D plus the report's code fixes,
     at the default 0.5 similarity cutoff.
  F  same as E with a 0.4 cutoff, to choose main.CHAT_SIMILARITY_CUTOFF.

Not a pytest test: makes real, billed OpenAI calls against the real local
index (~/.secondmind/index.lancedb). Run from backend/:

    uv run python3 scripts/ask_modes_eval.py [--set first|heldout] [--only A,B,C,D] [--out PATH]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import openai
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.llms.openai import OpenAI

import chat
import generation
import indexing
import llm

SM_HOME = Path.home() / ".secondmind"
COURSE_NAMES = {
    55710: "18-654 Software Testing & Operations",
    55016: "18-658 Software Requirements and Interaction Design",
    56350: "Advanced AI for Industry & Society",
}
DEFAULT_COURSE = 55710
MODEL = generation.DEFAULT_MODEL
TEMPERATURE = 0.1  # llama_index's OpenAI default, which mode A already uses
MAX_TOOL_ROUNDS = 4

# Each case is one chat. Single-question cases have one turn.
# kind: course_fact | concept_covered | not_in_course | trap | study_help | follow_up
CASES = [
    # Facts about the course: must come from the materials, never guessed.
    {"id": "F1", "kind": "course_fact", "turns": ["When is the midterm exam?"]},
    {"id": "F2", "kind": "course_fact", "turns": ["How much is the final exam worth?"]},
    {"id": "F3", "kind": "course_fact", "turns": ["What happens if I submit an assignment late?"]},
    {"id": "F4", "kind": "course_fact", "turns": ["When are the TA office hours?"]},
    {"id": "F5", "kind": "course_fact", "turns": ["Can I use ChatGPT for my assignments in this course?"]},
    {"id": "F6", "kind": "course_fact", "turns": ["What did the professor say about boundary values in class?"]},
    {"id": "F7", "kind": "course_fact", "turns": ["How many people can be on a project team?"]},
    # Concepts the course teaches.
    {"id": "K1", "kind": "concept_covered", "turns": ["What is the difference between a stub and a mock?"]},
    {"id": "K2", "kind": "concept_covered", "turns": ["What is a fake object in testing?"]},
    {"id": "K3", "kind": "concept_covered", "turns": ["What is combinatorial testing?"]},
    {"id": "K4", "kind": "concept_covered", "turns": ["What is test-driven development?"]},
    {"id": "K5", "kind": "concept_covered", "turns": ["What is dependency injection and why does it help testing?"]},
    # Concepts the course materials don't explain (yet).
    {"id": "G1", "kind": "not_in_course", "turns": ["How does mutation testing work?"]},
    {"id": "G2", "kind": "not_in_course", "turns": ["What is property-based testing?"]},
    {"id": "G3", "kind": "not_in_course", "turns": ["How does Docker layer caching work?"]},
    {"id": "G4", "kind": "not_in_course", "turns": ["What is the difference between Kubernetes and Docker Swarm?"]},
    # Traps: course facts that are NOT in the materials. The right answer is "I couldn't find that".
    {"id": "T1", "kind": "trap", "turns": ["When is Assignment 5 due?"]},
    {"id": "T2", "kind": "trap", "turns": ["Who is the guest lecturer for the operational excellence class?"]},
    {"id": "T3", "kind": "trap", "turns": ["What grade did I get on A0?"]},
    # Study help.
    {"id": "S1", "kind": "study_help", "turns": ["Explain test doubles to me like I'm new to programming."]},
    {"id": "S2", "kind": "study_help", "turns": ["Quiz me with 3 short questions on test doubles."]},
    # Follow-ups: only the later turns are the real test.
    {
        "id": "M1",
        "kind": "follow_up",
        "turns": ["What kinds of test doubles does the course cover?", "Explain the second one."],
    },
    {"id": "M2", "kind": "follow_up", "turns": ["When is the midterm?", "And the final?"]},
    {
        "id": "M3",
        "kind": "follow_up",
        "turns": [
            "What are boundary values?",
            "Give me a simple example with a function that takes a person's age.",
        ],
    },
    {
        "id": "M4",
        "kind": "follow_up",
        "turns": [
            "What is the difference between a stub and a mock?",
            "Which one should I use to check that my code sends an email?",
        ],
    },
    {"id": "M5", "kind": "follow_up", "turns": ["How is the course graded?", "Which part is worth the most?"]},
    {
        "id": "M6",
        "kind": "follow_up",
        "turns": ["What is test-driven development?", "Why does that help?", "When is the project due?"],
    },
]

# Held-out set, written after all four prompts were frozen, to check whether
# the first run's recommendation (D) holds on questions D was never tuned on.
# Two of the three courses here were never used in the first run.
REQ, AI, TST = 55016, 56350, 55710
HELDOUT_CASES = [
    # 18-658 Software Requirements and Interaction Design
    {"id": "H1", "course": REQ, "kind": "course_fact", "turns": ["When is the final exam and what format is it?"]},
    {"id": "H2", "course": REQ, "kind": "course_fact", "turns": ["Are the Friday recitations mandatory?"]},
    {"id": "H3", "course": REQ, "kind": "course_fact", "turns": ["What textbook do I need for this class?"]},
    {"id": "H4", "course": REQ, "kind": "course_fact", "turns": ["How long should our field project presentation be?"]},
    {"id": "H5", "course": REQ, "kind": "concept_covered", "turns": ["What makes a good storyboard?"]},
    {"id": "H6", "course": REQ, "kind": "concept_covered", "turns": ["How many users do I need for a usability test?"]},
    {"id": "H7", "course": REQ, "kind": "not_in_course", "turns": ["What are Nielsen's 10 usability heuristics? List them."]},
    {"id": "H8", "course": REQ, "kind": "trap", "turns": ["What are Professor Péraire's office hours?"]},
    {
        "id": "H9",
        "course": REQ,
        "kind": "follow_up",
        "turns": [
            "What are the grading weights in this course?",
            "Which single component is worth the most?",
            "And how much is attendance worth?",
        ],
    },
    {
        "id": "H10",
        "course": REQ,
        "kind": "follow_up",
        "turns": ["What are the deliverables for Task 3?", "Which of those involves a video?", "How long can it be?"],
    },
    # Advanced AI for Industry & Society
    {"id": "H11", "course": AI, "kind": "course_fact", "turns": ["What are the Big Four AI conferences according to the course?"]},
    {"id": "H12", "course": AI, "kind": "course_fact", "turns": ["How many students can be on a project team?"]},
    {"id": "H13", "course": AI, "kind": "course_fact", "turns": ["Which citation style should I pick in Zotero?"]},
    {"id": "H14", "course": AI, "kind": "course_fact", "turns": ["How recent should the papers in my literature search be?"]},
    {"id": "H15", "course": AI, "kind": "trap", "turns": ["When is the Sprint 3 deliverable due?"]},
    {"id": "H16", "course": AI, "kind": "trap", "turns": ["What percentage of my grade is the LLM certificate?"]},
    {"id": "H17", "course": AI, "kind": "not_in_course", "turns": ["What is a reranker and why would I use one in a RAG pipeline?"]},
    {
        "id": "H18",
        "course": AI,
        "kind": "follow_up",
        "turns": ["What is the BrainEEG research project about?", "Does their model beat the baseline?"],
    },
    {
        "id": "H19",
        "course": AI,
        "kind": "follow_up",
        "turns": [
            "What does the Sprint 1 individual assignment ask me to do?",
            "Show me what a filled-in value proposition looks like, using a made-up bike-sharing app.",
        ],
    },
    # 18-654 Software Testing & Operations, topics the first run didn't ask about
    {"id": "H20", "course": TST, "kind": "course_fact", "turns": ["Which IDE and build tool does the instructor use for starter code?"]},
    {
        "id": "H21",
        "course": TST,
        "kind": "course_fact",
        "turns": ["How many slip days do I get, and can I use them on the Super-Mutant milestones?"],
    },
    {"id": "H22", "course": TST, "kind": "concept_covered", "turns": ["What is the hyperassertion problem and how do I fix it?"]},
    {"id": "H23", "course": TST, "kind": "concept_covered", "turns": ["Which kind of test double is the least intrusive?"]},
    {"id": "H24", "course": TST, "kind": "not_in_course", "turns": ["How do I set up JaCoCo in a Maven project?"]},
    {"id": "H25", "course": TST, "kind": "trap", "turns": ["What did the professor cover in Class #2?"]},
    {
        "id": "H26",
        "course": TST,
        "kind": "follow_up",
        "turns": ["What does 'stub queries, mock actions' mean?", "Show me a short Java example of the second part."],
    },
]

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

PROMPT_B = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Search the course materials before answering. You can search more than once with different wording.
- Answer only with what the searches return. Cite every factual claim with its source number, like [2].
- If the materials don't cover it, say so plainly. Don't use outside knowledge.
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

PROMPT_C = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Search first whenever the question could be covered by the course: concepts taught, policies, dates, \
assignments, what was said in class. You can search more than once with different wording.
- Facts about this course (dates, grading, policies, deadlines, assignments, staff, what was said in class) \
must come only from search results, with citations like [2]. Never guess them. If the search doesn't find \
them, say you couldn't find it in the course materials.
- When explaining a concept, prefer the course's own material and cite it. If the course doesn't cover it, \
or the student asks for a simpler explanation or an extra example, you may use your general knowledge. Put \
that part after a line that says "General knowledge (not from your course materials):".
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

PROMPT_D = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Always search the course materials before answering, including for follow-up questions. You can search \
more than once with different wording. The only exception is when the student only asks you to reformat \
or shorten your previous answer.
- Facts about this course (dates, grading, weights, policies, deadlines, assignments, staff, what was said \
in class) must come only from search results. Copy numbers and dates exactly as the source states them. If \
the source text looks garbled or incomplete, say so instead of guessing. If you can't find it, say you \
couldn't find it in the course materials.
- Only cite a source for a claim that source actually states. Never add a citation to general knowledge.
- Your answer has up to two parts:
  1. What the course materials say, with citations. Leave this part out if they say nothing relevant, and \
say so in one sentence.
  2. Only if it helps (the course doesn't cover it, or the student asked for a simpler explanation or an \
extra example): a part that starts with the line "General knowledge (not from your course materials):". \
Everything you add from your own knowledge goes here, and nothing without a citation goes above it.
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

CITATION_MARK = re.compile(r"\[(\d+)\]")


def source_label(node_with_score) -> str:
    return generation.build_citations([node_with_score])[0]["label"]


# --- mode A: today's pipeline, question only -------------------------------


def run_a(index, question: str, _history: list[dict], _course_name: str) -> dict:
    # Token counts only register through the global callback manager.
    counter = TokenCountingHandler()
    Settings.callback_manager = CallbackManager([counter])
    llm = OpenAI(model=MODEL, api_key=generation._get_llm_key())
    engine = CitationQueryEngine.from_args(
        index,
        llm=llm,
        retriever=generation.HybridRetriever(index),
        citation_qa_template=generation.ANSWER_FIRST_TEMPLATE,
        streaming=False,
    )
    start = time.perf_counter()
    response = engine.query(question)
    elapsed = time.perf_counter() - start
    citations = generation.build_citations(response.source_nodes)
    answer = str(response) if citations else generation.NOT_COVERED_MESSAGE
    return {
        "answer": answer,
        "searches": [question],
        "sources": [c["label"] for c in citations],
        "seconds": round(elapsed, 2),
        "llm_calls": len(counter.llm_token_counts),
        "prompt_tokens": counter.prompt_llm_token_count,
        "completion_tokens": counter.completion_llm_token_count,
    }


# --- modes B and C: tool loop ------------------------------------------------


def run_tool_loop(index, question: str, history: list[dict], system_prompt: str) -> dict:
    client = openai.OpenAI(api_key=generation._get_llm_key())
    retriever = generation.HybridRetriever(index)
    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({"role": "user", "content": question})

    searches: list[str] = []
    sources: list[str] = []  # sources[n-1] is source number n
    prompt_tokens = completion_tokens = llm_calls = 0
    start = time.perf_counter()
    for round_num in range(MAX_TOOL_ROUNDS + 1):
        kwargs = {"model": MODEL, "messages": messages, "temperature": TEMPERATURE}
        if round_num < MAX_TOOL_ROUNDS:
            kwargs["tools"] = [SEARCH_TOOL]
        response = client.chat.completions.create(**kwargs)
        llm_calls += 1
        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        message = response.choices[0].message
        if not message.tool_calls:
            answer = message.content or ""
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            query = json.loads(call.function.arguments).get("query", "")
            searches.append(query)
            nodes = retriever.retrieve(query)
            if not nodes:
                result = "No matching course material found."
            else:
                parts = []
                for n in nodes:
                    sources.append(source_label(n))
                    parts.append(f"[{len(sources)}] {sources[-1]}\n{n.node.get_content()[:1500]}")
                result = "\n\n".join(parts)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    elapsed = time.perf_counter() - start

    cited = sorted({int(m) for m in CITATION_MARK.findall(answer)})
    return {
        "answer": answer,
        "searches": searches,
        "sources": [sources[i - 1] for i in cited if 0 < i <= len(sources)],
        "seconds": round(elapsed, 2),
        "llm_calls": llm_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def run_b(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_B.format(course_name=course_name))


def run_c(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_C.format(course_name=course_name))


def run_d(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_D.format(course_name=course_name))


def run_shipped(index, question, history, course_name, cutoff):
    searches: list[str] = []
    base_search = chat.make_search(index, cutoff)

    def search(query):
        searches.append(query)
        return base_search(query)

    start = time.perf_counter()
    events = list(chat.answer(question, history, course_name, search, llm.OpenAIProvider(temperature=TEMPERATURE)))
    elapsed = time.perf_counter() - start
    final = next(e for e in events if "citations" in e)
    return {
        "answer": "".join(e.get("delta", "") for e in events),
        "searches": searches,
        "sources": [c["label"] for c in final["citations"]],
        "seconds": round(elapsed, 2),
        "llm_calls": None,  # not exposed by the provider interface
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def run_e(index, question, history, course_name):
    return run_shipped(index, question, history, course_name, 0.5)


def run_f(index, question, history, course_name):
    return run_shipped(index, question, history, course_name, 0.4)


MODES = {"A": run_a, "B": run_b, "C": run_c, "D": run_d, "E": run_e, "F": run_f}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="A,B,C")
    parser.add_argument("--cases", default="", help="comma-separated case ids; default all")
    parser.add_argument("--set", default="first", choices=["first", "heldout"])
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent.parent / "docs/evaluations/2026-09-23-ask-modes/results.json"),
    )
    args = parser.parse_args()
    modes = args.only.split(",")
    wanted = set(filter(None, args.cases.split(",")))

    cases = HELDOUT_CASES if args.set == "heldout" else CASES
    indexes = {}
    results = []
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        course_id = case.get("course", DEFAULT_COURSE)
        if course_id not in indexes:
            indexes[course_id] = indexing.load_index(SM_HOME / "index.lancedb", f"course_{course_id}")
        index = indexes[course_id]
        for mode in modes:
            history: list[dict] = []
            for turn_num, question in enumerate(case["turns"], start=1):
                out = MODES[mode](index, question, history, COURSE_NAMES[course_id])
                history.append({"question": question, "answer": out["answer"]})
                results.append({"case": case["id"], "course": course_id, "kind": case["kind"], "turn": turn_num, "mode": mode, "question": question, **out})
                print(f"[{case['id']}.{turn_num} {mode}] {out['seconds']}s  searches={out['searches']}", flush=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {len(results)} results to {out_path}")


if __name__ == "__main__":
    main()
