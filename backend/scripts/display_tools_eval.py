"""Does chat show its cards when it should, and only then? Step 6 of
docs/plans/2026-10-28-chat-generative-ui.md; write-up in
docs/evaluations/2026-10-28-display-tools/report.md.

Runs 21 labelled questions through the shipped chat.answer, with the real
local index for search and the real Canvas assignments for show_deadlines.
show_quiz is stubbed: it records the call and returns a fake artifact, so
the run doesn't write 11 quizzes (study.py has its own evaluation).

Eleven of the 21 questions should show a card. The other half are near misses that
shouldn't: questions about the course's own quizzes and exams, one
assignment's content or due date, plain concept questions, and a request
for graded work.

Not a pytest test: real, billed model calls. Run from backend/:

    uv run python3 scripts/display_tools_eval.py [--provider openai|copilot] [--model gpt-4.1] [--course 55016] [--out PATH]
"""

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import canvas
import chat
import indexing
import llm
import main
import providers

SM_HOME = Path.home() / ".secondmind"
COURSE_NAMES = {55016: "18-658 Software Requirements and Interaction Design"}

# (question, the card it should show: "deadlines", "quiz" or None)
QUESTIONS = [
    ("What's due this week?", "deadlines"),
    ("Do I have anything due in the next few days?", "deadlines"),
    ("What should I work on this weekend?", "deadlines"),
    ("Any deadlines coming up?", "deadlines"),
    ("Which assignments haven't I submitted yet?", "deadlines"),
    ("Quiz me on user stories", "quiz"),
    ("Can you test me on use cases?", "quiz"),
    ("Give me some practice questions on requirements elicitation", "quiz"),
    ("I want to practice for the midterm. Quiz me on Planguage", "quiz"),
    ("Make me a hard quiz about heuristic evaluation", "quiz"),
    ("Quiz me with 15 questions on use cases", "quiz"),
    ("What's on the midterm exam?", None),
    ("When is the midterm?", None),
    ("What is a user story?", None),
    ("How is the final presentation graded?", None),
    ("What does the Heuristic Evaluation assignment ask for?", None),
    ("When is the Heuristic Evaluation due?", None),
    ("Are the in-class quizzes graded?", None),
    ("Explain the difference between functional and non-functional requirements", None),
    ("Write my answers for the User Stories in-class deliverable", None),
    ("How many quizzes are there in this course?", None),
]


def make_provider(name: str, model: str | None):
    provider = providers.PROVIDERS[name]
    if model:
        provider = dataclasses.replace(provider, model=model)
    if name == "copilot":
        import copilot_llm

        return copilot_llm.CopilotProvider(provider)
    return llm.OpenAIProvider(provider)


def run(provider_name: str, model: str | None, course_id: int) -> dict:
    provider = make_provider(provider_name, model)
    index = indexing.load_index(SM_HOME / "index.lancedb", f"course_{course_id}")
    search = chat.make_search(index, main.CHAT_SIMILARITY_CUTOFF)
    rows = [canvas.assignment_summary(a) for a in canvas.list_assignments(course_id)]
    course_name = COURSE_NAMES.get(course_id, f"course {course_id}")

    results = []
    for question, expected in QUESTIONS:
        quizzes = []

        def start_quiz(options):
            quizzes.append(options)
            return {"id": f"quiz-eval{len(quizzes)}", "status": "generating"}

        started = time.monotonic()
        events = list(
            chat.answer(question, [], course_name, search, provider, assignments=lambda: rows, start_quiz=start_quiz)
        )
        shown = [e["ui"]["component"] for e in events if "ui" in e]
        results.append(
            {
                "question": question,
                "expected": expected,
                "shown": shown,
                "quiz_options": quizzes,
                "answer": "".join(e.get("delta", "") for e in events),
                "mentions_study_panel": "study panel" in "".join(e.get("delta", "") for e in events).lower(),
                "seconds": round(time.monotonic() - started, 1),
            }
        )
        mark = "ok " if shown == ([expected] if expected else []) else "MISS"
        print(f"{mark} {question!r}: expected {expected}, shown {shown}", flush=True)
    return {"provider": provider_name, "model": model or providers.PROVIDERS[provider_name].model, "course": course_id, "results": results}


def score(results: list[dict]) -> dict:
    out = {}
    for card in ("deadlines", "quiz"):
        tp = sum(1 for r in results if r["expected"] == card and card in r["shown"])
        fp = sum(1 for r in results if r["expected"] != card and card in r["shown"])
        fn = sum(1 for r in results if r["expected"] == card and card not in r["shown"])
        out[card] = {
            "precision": round(tp / (tp + fp), 2) if tp + fp else None,
            "recall": round(tp / (tp + fn), 2) if tp + fn else None,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    # A quiz in chat is always 5 questions. The Study panel should come up
    # when the student asked for more, and only then.
    quiz_rows = [r for r in results if r["expected"] == "quiz"]
    out["study_panel_mentions"] = {
        "asked_for_more": [r["mentions_study_panel"] for r in quiz_rows if "15 questions" in r["question"]],
        "did_not_ask": sum(r["mentions_study_panel"] for r in quiz_rows if "15 questions" not in r["question"]),
    }
    out["exact"] = sum(1 for r in results if r["shown"] == ([r["expected"]] if r["expected"] else []))
    out["total"] = len(results)
    return out


def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="openai", choices=sorted(providers.PROVIDERS))
    parser.add_argument("--model", help="another model from the same provider, like gpt-4.1")
    parser.add_argument("--course", type=int, default=55016)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    run_data = run(args.provider, args.model, args.course)
    run_data["score"] = score(run_data["results"])
    print(json.dumps(run_data["score"], indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(run_data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main_cli()
