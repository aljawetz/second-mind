"""Listing questions before and after list_course_items (RAG gaps plan task 8).

"What are all the readings for Task 3?" needs every item, and a search only
returns the closest few passages. Each question here has a full answer taken
from the course's Canvas outline; an answer scores by how many of those items
it names. Read the answers too: the score doesn't catch invented items.

Runs the shipped chat (chat.answer) twice per question per variant, without
and with the listing tool, on gpt-4o-mini. Needs an index synced with the
whole course menu (course_sync after task 8), so pass the folder holding it:

    uv run python3 scripts/listing_eval.py --home /path/to/secondmind-copy --out /path/to/answers.json

Real, billed OpenAI calls (a few cents). The answers quote course material:
keep the output out of the repo (it is public).
"""

import argparse
import dataclasses
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chat
import course_items
import indexing
import llm
import providers
from eval_key import use_eval_key  # scripts/ is on the path when run as a script

COURSE_NAMES = {
    55016: "18-658 Software Requirements and Interaction Design",
    56350: "Advanced AI for Industry & Society",
}
CHAT_SIMILARITY_CUTOFF = 0.5  # main.CHAT_SIMILARITY_CUTOFF, without importing the server
TODAY = datetime.date(2026, 11, 15)

# id, course, question, the items a full answer names (a distinctive part of
# each name, matched case-insensitively). Written from the synced outline on
# 2026-11-15, before any run.
QUESTIONS = [
    ("L1", 55016, "What are all the readings for Task 3?", [
        "Lean Requirements", "Leffingwell - Use Cases", "Wiegers", "IxD Foundation", "Kano Analysis",
        "Kano Model", "landing page", "ads"]),
    ("L2", 55016, "List every resource I should use for Task 4 prototyping and backlog preparation.", [
        "About-Face", "UX Book - Prototyping", "Wireframes", "Gomoll", "UX Book - Evaluation", "Naumovich",
        "4C Model", "Wiegers", "Simmons", "Use-Case 2.0", "EARS"]),
    ("L3", 55016, "Which readings are listed for class preparation?", [
        "About-Face", "Lean Requirements", "mind map", "Wiegers", "UX Book Chapter 4", "Narrative Storyboard",
        "Kano Analysis", "MAUT", "landing page", "Wireframes", "UX Book - Evaluation", "4C Model",
        "Quantifying Quality", "Frontend Tools", "Dual Track"]),
    ("L4", 55016, "What pages are in the Task 1 module?", [
        "Innovation Project Objectives", "Task 1 Objectives", "Task 1 Plan of Attack", "Task 1 Resources",
        "Task 1: Submitting"]),
    ("L5", 55016, "What are all the Field Project assignments?", [
        "Selecting a Company", "Recruiting Interviewees", "Submitting Your Presentation Material"]),
    ("L6", 56350, "What materials are posted for the week 2 literature review?", [
        "Building RAG Agents", "ACM/IEEE", "Research Study", "Sample Literature Review", "Sample Table"]),
    ("L7", 56350, "List all the announcements in this course.", [
        "Self Evaluation", "Salesforce", "Startup World Cup", "Class This Tuesday", "Agentic AI Seminar",
        "Guest Speaker", "Stakeholder Interview", "AI Tool Budget", "Project Team Sheet", "Pre-Course Skill",
        "Sprint Task Submission", "Roll Call", "Reflection Survey"]),
    ("L8", 56350, "What are all the sprint deliverables?", [
        "Sprint 1 ", "Sprint 2 ", "Sprint 3 ", "Sprint 4 ", "Sprint 5 ", "Sprint 6 ", "Sprint 7 ", "Sprint 8 ",
        "Sprint 9 "]),
]


def found(answer: str, items: list[str]) -> list[str]:
    text = answer.lower().replace("**", "")
    return [item for item in items if item.lower() in text]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, help="folder with index.lancedb and courses/<id>/manifest.db")
    parser.add_argument("--out", required=True)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--model", default="gpt-4o-mini")
    args = parser.parse_args()
    use_eval_key()
    home = Path(args.home)
    provider = llm.OpenAIProvider(dataclasses.replace(providers.OPENAI, model=args.model, fixed_temperature=False))
    results = []
    for qid, course_id, question, items in QUESTIONS:
        search = chat.make_search(indexing.load_index(home / "index.lancedb", f"course_{course_id}"), CHAT_SIMILARITY_CUTOFF)
        for variant in ("without", "with"):
            for run in range(args.runs):
                calls = []
                list_items = None
                if variant == "with":
                    def list_items(topic, types, c=course_id, calls=calls):
                        calls.append({"topic": topic, "types": types})
                        return course_items.list_for_course(home, c, topic, types)

                start = time.perf_counter()
                events = list(chat.answer(question, [], COURSE_NAMES[course_id], search, provider, today=TODAY, list_items=list_items))
                answer = "".join(e.get("delta", "") for e in events)
                usage = next(e for e in events if "citations" in e).get("usage") or {}
                hits = found(answer, items)
                results.append({
                    "id": qid, "variant": variant, "run": run, "question": question, "answer": answer,
                    "list_calls": calls, "found": len(hits), "of": len(items), "missed": [i for i in items if i not in hits],
                    "seconds": round(time.perf_counter() - start, 1), "usage": usage,
                })
                print(f"{qid} {variant:7} run {run}: {len(hits)}/{len(items)}  {results[-1]['seconds']}s  {calls}", flush=True)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print()
    for variant in ("without", "with"):
        rows = [r for r in results if r["variant"] == variant]
        total = sum(r["found"] for r in rows)
        possible = sum(r["of"] for r in rows)
        tokens = sum(r["usage"].get("prompt_tokens", 0) + r["usage"].get("completion_tokens", 0) for r in rows)
        seconds = sorted(r["seconds"] for r in rows)[len(rows) // 2]
        print(f"{variant:7}: {total}/{possible} items named ({total / possible:.0%}), median {seconds}s, {tokens} tokens")


if __name__ == "__main__":
    main()
