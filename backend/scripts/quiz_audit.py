"""Audit generated quizzes for the Sprint 7 validation report.

For each pilot course it writes a medium and a hard quiz through the same
study.generate the app uses, then checks every question two ways with a model:

  answerable  gpt-4o sees the cited passage and must pick the right option.
              A question it cannot answer from its own passage is not grounded.
  unaided     gpt-4o-mini sees only the question and options, no passage. If it
              still picks the right option, a student could probably guess it.
              Chance is 25% for four options.

It also checks a common tell: the correct option being the longest one.

Writes, next to --out:
  <stem>-items.json         every question with its passage (quotes course text; stays local)
  <stem>-sheet.csv          a random sample for people to hand-grade (quotes course text; stays local)
  <stem>-key.csv            the marked answers for that sample, kept apart so graders can answer blind
  <stem>-grades.json        counts only (safe to commit)

Not a pytest test: real, billed OpenAI calls against the local index. From backend/:

    uv run python3 scripts/quiz_audit.py [--courses 55710,56350] [--count 10] [--sample 20]
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import llm
import providers
import study

SM_HOME = Path.home() / ".secondmind"
COURSE_NAMES = {55710: "18-654 Software Testing & Operations", 56350: "Advanced AI for Industry & Society"}
DIFFICULTIES = ("medium", "hard")
CHECK_MODEL = "gpt-4o"
UNAIDED_MODEL = providers.OPENAI.model

PICK_SYSTEM = (
    "You answer one multiple-choice question. Reply with JSON only: "
    '{"answer": <number of the best option, 1-4>}'
)


def pick(client, model: str, item: dict, passage: str | None) -> int | None:
    options = "\n".join(f"{n}. {o['text']}" for n, o in enumerate(item["options"], 1))
    material = f"Passage:\n{passage}\n\n" if passage else ""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": PICK_SYSTEM},
            {"role": "user", "content": f"{material}Question: {item['question']}\n{options}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        answer = json.loads(response.choices[0].message.content or "{}").get("answer")
    except json.JSONDecodeError:
        return None
    return answer if isinstance(answer, int) and 1 <= answer <= len(item["options"]) else None


def key_of(item: dict) -> int:
    return next(n for n, o in enumerate(item["options"], 1) if o["correct"])


def audit_item(client, item: dict) -> dict:
    key = key_of(item)
    lengths = [len(o["text"]) for o in item["options"]]
    return {
        "answerable": pick(client, CHECK_MODEL, item, item["passage"]) == key,
        "unaided_correct": pick(client, UNAIDED_MODEL, item, None) == key,
        "correct_is_longest": lengths[key - 1] == max(lengths) and lengths.count(max(lengths)) == 1,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--courses", default="55710,56350")
    parser.add_argument("--count", type=int, default=10, help="questions per quiz (one quiz per difficulty)")
    parser.add_argument("--sample", type=int, default=20, help="questions in the hand-grading sheet")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--out", default=str(Path(__file__).parent.parent.parent / "docs/evaluations/2026-10-sprint7/quiz-audit.json")
    )
    args = parser.parse_args()
    rng = random.Random(args.seed)
    client = providers.openai_client(providers.OPENAI)
    model = llm.OpenAIProvider(providers.OPENAI)

    all_items, rows = [], []
    for course_id in (int(c) for c in args.courses.split(",")):
        chunks = study.material_chunks(SM_HOME / "index.lancedb", course_id, None)
        if not chunks:
            print(f"[{course_id}] no indexed material, skipped")
            continue
        material = study.select_material(chunks)
        for difficulty in DIFFICULTIES:
            written = study.generate(
                "quiz", material, count=args.count, difficulty=difficulty, topic="", llm=model, rng=random.Random(args.seed)
            )
            stats = written["stats"]
            print(f"[{course_id} {difficulty}] kept={len(written['items'])} stats={stats}", flush=True)
            for n, item in enumerate(written["items"], 1):
                checked = audit_item(client, item)
                all_items.append({"course": course_id, "difficulty": difficulty, "n": n, **item, **checked})
            rows.append(
                {
                    "course": course_id,
                    "difficulty": difficulty,
                    "kept": len(written["items"]),
                    "generated": stats["generated"],
                    "unsourced": stats["unsourced"],
                    "unsupported": stats["unsupported"],
                    "malformed": stats["malformed"],
                    "checked": stats["checked"],
                }
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem = out.with_suffix("")

    # Counts only: safe to commit.
    def rate(items, field):
        return round(sum(1 for i in items if i[field]) / len(items), 3) if items else None

    summary = {
        "pipeline": rows,
        "overall": {
            "questions": len(all_items),
            "answerable_from_passage": rate(all_items, "answerable"),
            "answered_correctly_without_passage": rate(all_items, "unaided_correct"),
            "correct_option_is_longest": rate(all_items, "correct_is_longest"),
            "chance": 0.25,
        },
        "by_course_difficulty": {
            f"{c}-{d}": {
                "questions": len(sub),
                "answerable_from_passage": rate(sub, "answerable"),
                "answered_correctly_without_passage": rate(sub, "unaided_correct"),
            }
            for c in sorted({i["course"] for i in all_items})
            for d in DIFFICULTIES
            if (sub := [i for i in all_items if i["course"] == c and i["difficulty"] == d])
        },
    }
    grades_path = stem.with_name(f"{stem.name}-grades.json")
    grades_path.write_text(json.dumps(summary, indent=2))
    stem.with_name(f"{stem.name}-items.json").write_text(json.dumps(all_items, indent=2))

    sample = rng.sample(all_items, min(args.sample, len(all_items)))
    sheet_path = stem.with_name(f"{stem.name}-sheet.csv")
    with sheet_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "course", "difficulty", "question", "option_1", "option_2", "option_3", "option_4",
             "your_answer_without_material (1-4, fill this FIRST, before the passage and key)", "source",
             "passage_excerpt", "grader", "answerable_from_passage (y/n)", "guessable_without_material (y/n)", "notes"]
        )
        for i, item in enumerate(sample, 1):
            writer.writerow(
                [f"Q{i}", item["course"], item["difficulty"], item["question"], *[o["text"] for o in item["options"]],
                 "", item["citation"].get("label", ""), item["passage"][:700], "", "", "", ""]
            )
    # Kept apart so graders can answer without seeing the key.
    key_path = stem.with_name(f"{stem.name}-key.csv")
    with key_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "marked_correct_option"])
        for i, item in enumerate(sample, 1):
            writer.writerow([f"Q{i}", key_of(item)])

    print(json.dumps(summary["overall"], indent=2))
    print(f"wrote {grades_path} (counts only), items and sheet (local only: {sheet_path})")


if __name__ == "__main__":
    main()
