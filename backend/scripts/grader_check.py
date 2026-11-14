"""Check the answer judge against hand grades (RAG gaps plan, task 6).

Sprint 7 hand-graded 10 answers and agreed with the gpt-4o judge on 4, and
Sprint 8 called the judge too noisy to trust. This script measures how
often the judge agrees with a person, in two formats:

  pointwise  the judge ask_modes_eval.py already uses: good / ok / bad for
             one answer against the gold answer.
  pairwise   the RAG course's format: two answers to the same turn side by
             side, verdict first. Asked in both orders; a verdict that flips
             with the order counts as a tie.

The answers are sprint9-chat turns from the shipped chat (mode E) and the
no-search baseline (mode G). Turns are split by chat into a tuning half,
the only half to look at while changing a judge prompt, and a reporting
half, scored once when the prompts are settled.

Run from backend/ (DIR is docs/evaluations/2026-11-grader-check):

  1. Answers, real billed calls (about 80 chat calls):
       uv run python3 scripts/ask_modes_eval.py --set sprint9-chat --only E,G --no-judge --out DIR/answers.json
  2. The blind grading page and its key:
       uv run python3 scripts/grader_check.py sheet --answers DIR/answers.json --dir DIR
     Open DIR/grading.html in a browser, grade, and save the CSV it gives
     you as DIR/grades.csv.
  3. The judge, both formats (gpt-4o, about 80 calls):
       uv run python3 scripts/grader_check.py judge --answers DIR/answers.json --dir DIR --label v1
  4. Agreement, tuning half while prompts change, reporting half once:
       uv run python3 scripts/grader_check.py agree --dir DIR --label v1 --half tune

answers.json, grading.html, key.json, grades.csv and judge-*.json quote
course text or hold a free-text note, so they stay local (the folder's
.gitignore). agree writes human-grades.json and agreement-*.json, which hold
grades and counts only.
"""

import argparse
import csv
import html
import io
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import ask_modes_eval  # noqa: E402

GRADES = ("good", "ok", "bad")
_RANK = {"good": 2, "ok": 1, "bad": 0}
SHIPPED, BASELINE = "E", "G"

# What the grader reads at the top of the sheet. The same three levels, in
# the same words, as JUDGE_PROMPT's "correct" axis, so both grade one thing.
RUBRIC = """Grade each answer against the gold answer: what the turn must say.
good: matches the gold answer's facts, is useful, and its sources make sense.
ok: not wrong, but unhelpful, incomplete, or unlabeled.
bad: wrong, made up, or fails to answer something it should have.
Then pick the answer that is better for the student, or tie if neither is."""

PAIRWISE_PROMPT = """You are comparing two chat-assistant answers to the same student question for an \
evaluation. You wrote neither and have no stake in either. Judge them against the gold answer, not on how \
confident or polished they sound.

Course: {course_name}
Earlier questions in this chat: {earlier}
Question: {question}
Gold answer / correct behavior: {gold}

Answer 1:
{answer_1}
Sources answer 1 cited: {sources_1}

Answer 2:
{answer_2}
Sources answer 2 cited: {sources_2}

Which answer is better for the student? The better answer states the gold answer's facts correctly and \
states no wrong or made-up course facts. If they are equally good or equally bad, it's a tie.

Return ONLY a JSON object, verdict first: {{"verdict": "1" | "2" | "tie", "reason": "one sentence"}}"""


# --- picking turns -------------------------------------------------------------


def select_turns(results: list[dict], cases: list[dict], *, n: int = 20, seed: int = 0) -> list[dict]:
    """n turns that both modes answered, half from tuning chats and half
    from reporting chats. Numbered 1..n in chat order, so a follow-up reads
    after the turn before it."""
    by_turn: dict[tuple[str, int], dict] = {}
    for row in results:
        if row["mode"] in (SHIPPED, BASELINE):
            by_turn.setdefault((row["case"], row["turn"]), {})[row["mode"]] = row
    case_by_id = {c["id"]: c for c in cases}
    complete = [k for k, v in by_turn.items() if len(v) == 2 and k[0] in case_by_id]

    rng = random.Random(seed)
    chat_ids = [c["id"] for c in cases if any(k[0] == c["id"] for k in complete)]
    rng.shuffle(chat_ids)
    half_of = {cid: ("tune" if i % 2 == 0 else "report") for i, cid in enumerate(chat_ids)}

    picked: list[tuple[str, int]] = []
    for half in ("tune", "report"):
        pool = sorted(k for k in complete if half_of[k[0]] == half)
        picked += rng.sample(pool, min(n // 2, len(pool)))

    order = {c["id"]: i for i, c in enumerate(cases)}
    picked.sort(key=lambda k: (order[k[0]], k[1]))
    items = []
    for number, (case_id, turn) in enumerate(picked, start=1):
        case = case_by_id[case_id]
        items.append(
            {
                "n": number,
                "case": case_id,
                "turn": turn,
                "half": half_of[case_id],
                "course": case["course"],
                "question": case["turns"][turn - 1],
                "earlier": case["turns"][: turn - 1],
                "gold": ask_modes_eval.turn_gold_answer(case, turn) or case.get("gold_answer") or "",
                "answers": by_turn[(case_id, turn)],
            }
        )
    return items


def assign_sides(items: list[dict], rng: random.Random) -> dict[int, dict[str, str]]:
    """{n: {"A": mode, "B": mode}}: which system's answer each side shows."""
    key = {}
    for item in items:
        a, b = (SHIPPED, BASELINE) if rng.random() < 0.5 else (BASELINE, SHIPPED)
        key[item["n"]] = {"A": a, "B": b}
    return key


# --- the grading page -------------------------------------------------------------


def render_sheet(items: list[dict], key: dict[int, dict[str, str]]) -> str:
    """A self-contained page: each turn's gold answer and its two answers,
    radio buttons, and a button that saves the grades as CSV. Nothing on it
    says which system wrote which answer."""
    e = html.escape
    turns = []
    for item in items:
        sides = key[item["n"]]
        earlier = "".join(f"<li>{e(q)}</li>" for q in item["earlier"])
        answers = []
        for side in ("A", "B"):
            row = item["answers"][sides[side]]
            sources = ", ".join(row.get("sources") or []) or "(none)"
            radios = "".join(
                f'<label><input type="radio" name="g{item["n"]}{side}" value="{g}"> {g}</label>' for g in GRADES
            )
            answers.append(
                f'<div class="answer"><h3>Answer {side}</h3><div class="text">{e(row["answer"])}</div>'
                f'<p class="sources">Sources cited: {e(sources)}</p><p class="radios">{radios}</p></div>'
            )
        better = "".join(
            f'<label><input type="radio" name="b{item["n"]}" value="{v}"> {label}</label>'
            for v, label in (("A", "A"), ("B", "B"), ("tie", "tie"))
        )
        turns.append(
            f'<section data-n="{item["n"]}"><h2>Turn {item["n"]}</h2>'
            + (f'<p class="muted">Earlier in this chat:</p><ol class="earlier">{earlier}</ol>' if earlier else "")
            + f'<p class="q"><b>Student:</b> {e(item["question"])}</p>'
            + f'<p class="gold"><b>Gold:</b> {e(item["gold"])}</p>'
            + f'<div class="pair">{"".join(answers)}</div>'
            + f'<p class="radios"><b>Better for the student:</b> {better}</p>'
            + f'<p><input class="note" name="n{item["n"]}" placeholder="Note (optional)"></p></section>'
        )
    rubric = "".join(f"<p>{e(line)}</p>" for line in RUBRIC.splitlines())
    return _PAGE.replace("{RUBRIC}", rubric).replace("{TURNS}", "\n".join(turns)).replace("{COUNT}", str(len(items)))


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Answer grading</title>
<style>
:root { --bg: #fbfaf7; --fg: #1d1d1b; --muted: #6b6b66; --line: #dcd9d0; --card: #ffffff; --accent: #1f5f5b; }
@media (prefers-color-scheme: dark) { :root { --bg: #171716; --fg: #ecebe6; --muted: #a3a29b; --line: #3a3935; --card: #22221f; --accent: #7cc4bd; } }
body { background: var(--bg); color: var(--fg); font: 15px/1.5 -apple-system, system-ui, sans-serif; margin: 0 auto; max-width: 1100px; padding: 16px; }
.rubric, section { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; margin: 16px 0; }
.rubric p { margin: 4px 0; }
h2 { margin: 0 0 8px; font-size: 17px; }
h3 { margin: 0 0 6px; font-size: 14px; color: var(--accent); }
.muted, .sources, .earlier { color: var(--muted); font-size: 13px; }
.gold { border-left: 3px solid var(--accent); padding-left: 8px; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 700px) { .pair { grid-template-columns: 1fr; } }
.answer { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
.text { white-space: pre-wrap; overflow-wrap: anywhere; }
.radios label { margin-right: 14px; white-space: nowrap; }
.note { width: 100%; box-sizing: border-box; padding: 6px; background: var(--bg); color: var(--fg); border: 1px solid var(--line); border-radius: 4px; }
.bar { position: sticky; bottom: 0; background: var(--bg); padding: 10px 0; border-top: 1px solid var(--line); display: flex; gap: 12px; align-items: center; }
button { background: var(--accent); color: var(--bg); border: 0; border-radius: 6px; padding: 8px 14px; font-size: 14px; cursor: pointer; }
</style></head><body>
<h1>Answer grading</h1>
<div class="rubric">{RUBRIC}<p class="muted">Your choices are kept in this browser as you go. When done, save the CSV.</p></div>
{TURNS}
<div class="bar"><button id="save">Save grades.csv</button><span id="done"></span></div>
<script>
const COUNT = {COUNT};
const STORE = "answer-grading-v1";
function load() { try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch (e) { return {}; } }
function persist(state) { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
const state = load();
document.querySelectorAll("input").forEach((input) => {
  const saved = state[input.name];
  if (input.type === "radio") input.checked = saved === input.value;
  else if (saved) input.value = saved;
  input.addEventListener("input", () => { state[input.name] = input.value; persist(state); progress(); });
});
function value(name) { return state[name] || ""; }
function progress() {
  let done = 0;
  for (let n = 1; n <= COUNT; n++) if (value(`g${n}A`) && value(`g${n}B`) && value(`b${n}`)) done++;
  document.getElementById("done").textContent = `${done} of ${COUNT} turns complete`;
}
function cell(text) { return /[",\\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text; }
document.getElementById("save").addEventListener("click", () => {
  const lines = ["n,grade_a,grade_b,better,note"];
  for (let n = 1; n <= COUNT; n++) lines.push([n, value(`g${n}A`), value(`g${n}B`), value(`b${n}`), cell(value(`n${n}`))].join(","));
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([lines.join("\\n") + "\\n"], { type: "text/csv" }));
  link.download = "grades.csv";
  link.click();
});
progress();
</script></body></html>
"""


# --- reading grades back -----------------------------------------------------------


def read_grades(csv_text: str, key: dict[int, dict[str, str]]) -> dict[int, dict[str, str]]:
    """{n: {"E": grade, "G": grade, "better": "E" | "G" | "tie"}} for every
    fully graded row; rows left blank are skipped."""
    human = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        n = int(row["n"])
        a, b, better = (row.get(k, "").strip() for k in ("grade_a", "grade_b", "better"))
        if not (a or b or better):
            continue
        if a not in GRADES or b not in GRADES or better not in ("A", "B", "tie"):
            raise ValueError(f"row {n}: grades must be good/ok/bad and better A/B/tie, got {a!r}, {b!r}, {better!r}")
        sides = key[n]
        human[n] = {sides["A"]: a, sides["B"]: b, "better": better if better == "tie" else sides[better]}
    return human


# --- agreement ------------------------------------------------------------------


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Agreement beyond chance between two graders; None when chance is
    already certain (both always used one and the same label)."""
    total = len(a)
    if not total:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / total
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[label] * cb[label] for label in set(a) | set(b)) / total**2
    if chance == 1:
        return None
    return (observed - chance) / (1 - chance)


def combine_orders(first: str, swapped: str) -> str:
    """The pairwise verdict, by mode, from the two orders. One that changes
    when the answers swap places followed the position, not the answer."""
    return first if first == swapped else "tie"


def preference(grade_e: str, grade_g: str) -> str:
    """Which answer two pointwise grades prefer."""
    if _RANK[grade_e] == _RANK[grade_g]:
        return "tie"
    return SHIPPED if _RANK[grade_e] > _RANK[grade_g] else BASELINE


def agreement(items: list[dict], human: dict, judged: dict, *, half: str) -> dict:
    """Counts for one half: the pointwise judge's grades against the human's,
    its grades turned into a preference, and the pairwise judge's verdict,
    each against the human's pick."""
    ns = [i["n"] for i in items if i["half"] == half and i["n"] in human and i["n"] in judged]
    people, judge = [], []
    confusion = {h: {j: 0 for j in GRADES} for h in GRADES}
    for n in ns:
        for mode in (SHIPPED, BASELINE):
            h, j = human[n][mode], judged[n]["pointwise"].get(mode)
            if j in GRADES:
                people.append(h)
                judge.append(j)
                confusion[h][j] += 1
    kappa = cohen_kappa(people, judge)
    as_pairs = [n for n in ns if all(judged[n]["pointwise"].get(m) in GRADES for m in (SHIPPED, BASELINE))]
    return {
        "half": half,
        "turns": len(ns),
        "pointwise": {
            "answers": len(people),
            "exact": sum(h == j for h, j in zip(people, judge)),
            "kappa": round(kappa, 3) if kappa is not None else None,
            "confusion": confusion,  # [human grade][judge grade]
        },
        "pointwise_as_pairs": {
            "turns": len(as_pairs),
            "agree": sum(
                preference(judged[n]["pointwise"][SHIPPED], judged[n]["pointwise"][BASELINE]) == human[n]["better"]
                for n in as_pairs
            ),
        },
        "pairwise": {"turns": len(ns), "agree": sum(judged[n]["pairwise"] == human[n]["better"] for n in ns)},
    }


def shareable_grades(items: list[dict], human: dict) -> list[dict]:
    """The hand grades by case and turn, with no course text: safe to commit."""
    return [
        {
            "case": i["case"],
            "turn": i["turn"],
            "half": i["half"],
            "human_E": human[i["n"]][SHIPPED],
            "human_G": human[i["n"]][BASELINE],
            "human_better": human[i["n"]]["better"],
        }
        for i in items
        if i["n"] in human
    ]


# --- the judge (billed calls) -------------------------------------------------------


def pairwise_once(client, item: dict, first: str, second: str) -> tuple[str, str]:
    """(verdict by mode, reason) with `first`'s answer shown as answer 1."""
    one, two = item["answers"][first], item["answers"][second]
    prompt = PAIRWISE_PROMPT.format(
        course_name=ask_modes_eval.COURSE_NAMES[item["course"]],
        earlier=" | ".join(item["earlier"]) or "(none)",
        question=item["question"],
        gold=item["gold"],
        answer_1=one["answer"],
        sources_1=", ".join(one.get("sources") or []) or "(none)",
        answer_2=two["answer"],
        sources_2=", ".join(two.get("sources") or []) or "(none)",
    )
    response = client.chat.completions.create(
        model=ask_modes_eval.JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        response_format={"type": "json_object"},
    )
    try:
        reply = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        reply = {}
    verdict = {"1": first, "2": second, "tie": "tie"}.get(str(reply.get("verdict")), "tie")
    return verdict, str(reply.get("reason", ""))


def judge_item(client, item: dict, case: dict) -> dict:
    pointwise = {}
    for mode in (SHIPPED, BASELINE):
        row = item["answers"][mode]
        grade = ask_modes_eval.judge(
            client, ask_modes_eval.COURSE_NAMES[item["course"]], case, item["question"], row["answer"], row.get("sources") or [], item["gold"]
        )
        pointwise[mode] = grade["correct"]
    first, first_reason = pairwise_once(client, item, SHIPPED, BASELINE)
    swapped, swapped_reason = pairwise_once(client, item, BASELINE, SHIPPED)
    return {
        "pointwise": pointwise,
        "pairwise": combine_orders(first, swapped),
        "orders": {"shipped_first": first, "baseline_first": swapped},
        "reasons": [first_reason, swapped_reason],
    }


# --- commands ---------------------------------------------------------------------


def _items_from_key(answers_path: Path, dir_: Path) -> tuple[list[dict], dict]:
    saved = json.loads((dir_ / "key.json").read_text())
    results = json.loads(answers_path.read_text())
    cases = ask_modes_eval.cases_for("sprint9-chat")
    items = select_turns(results, cases, n=saved["turns"], seed=saved["seed"])
    key = {int(n): sides for n, sides in saved["sides"].items()}
    picked = [[i["case"], i["turn"], i["half"]] for i in items]
    if picked != saved["picked"]:
        sys.exit("answers.json no longer gives the turns the sheet was made from; grade a new sheet")
    return items, key


def cmd_sheet(args) -> None:
    dir_ = Path(args.dir)
    key_path = dir_ / "key.json"
    if key_path.exists() and not args.force:
        sys.exit(f"{key_path} exists: a new sheet would reshuffle the sides of grades already given. --force to replace it.")
    results = json.loads(Path(args.answers).read_text())
    items = select_turns(results, ask_modes_eval.cases_for("sprint9-chat"), n=args.turns, seed=args.seed)
    key = assign_sides(items, random.Random(args.seed))
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "grading.html").write_text(render_sheet(items, key))
    key_path.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "turns": args.turns,
                "picked": [[i["case"], i["turn"], i["half"]] for i in items],
                "sides": key,
            },
            indent=2,
        )
    )
    halves = Counter(i["half"] for i in items)
    print(f"{len(items)} turns ({halves['tune']} tuning, {halves['report']} reporting). Open {dir_ / 'grading.html'}")


def cmd_judge(args) -> None:
    from eval_key import use_eval_key

    import providers

    print("OpenAI key: " + ("the evaluation key" if use_eval_key() else "the app's (no evaluation key stored)"), flush=True)
    dir_ = Path(args.dir)
    items, _ = _items_from_key(Path(args.answers), dir_)
    cases = {c["id"]: c for c in ask_modes_eval.cases_for("sprint9-chat")}
    client = providers.openai_client(providers.OPENAI)
    with ThreadPoolExecutor(max_workers=8) as pool:
        judged = dict(zip((i["n"] for i in items), pool.map(lambda i: judge_item(client, i, cases[i["case"]]), items)))
    out = dir_ / f"judge-{args.label}.json"
    out.write_text(json.dumps(judged, indent=2))
    flips = sum(j["orders"]["shipped_first"] != j["orders"]["baseline_first"] for j in judged.values())
    print(f"judged {len(judged)} turns ({flips} pairwise verdicts changed with the order) -> {out}")


def _print_agreement(result: dict) -> None:
    p, pp, pw = result["pointwise"], result["pointwise_as_pairs"], result["pairwise"]
    print(f"\n## {result['half']} half, {result['turns']} turns\n")
    print(f"Pointwise grades: {p['exact']} of {p['answers']} answers the same, kappa {p['kappa']}")
    print("  human \\ judge   " + "  ".join(f"{g:>4}" for g in GRADES))
    for h in GRADES:
        print(f"  {h:15s} " + "  ".join(f"{p['confusion'][h][j]:>4}" for j in GRADES))
    print(f"Better answer, from pointwise grades: {pp['agree']} of {pp['turns']} turns agree")
    print(f"Better answer, pairwise judge:        {pw['agree']} of {pw['turns']} turns agree")


def cmd_agree(args) -> None:
    dir_ = Path(args.dir)
    saved = json.loads((dir_ / "key.json").read_text())
    key = {int(n): sides for n, sides in saved["sides"].items()}
    human = read_grades((dir_ / "grades.csv").read_text(), key)
    judged = {int(n): v for n, v in json.loads((dir_ / f"judge-{args.label}.json").read_text()).items()}
    items = [
        {"n": n, "case": case, "turn": turn, "half": half}
        for n, (case, turn, half) in enumerate(saved["picked"], start=1)
    ]
    result = agreement(items, human, judged, half=args.half)
    _print_agreement(result)
    (dir_ / f"agreement-{args.label}-{args.half}.json").write_text(json.dumps(result, indent=2))
    (dir_ / "human-grades.json").write_text(json.dumps(shareable_grades(items, human), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sheet = sub.add_parser("sheet", help="pick the turns and write the blind grading page and its key")
    sheet.add_argument("--answers", required=True)
    sheet.add_argument("--dir", required=True)
    sheet.add_argument("--turns", type=int, default=20)
    sheet.add_argument("--seed", type=int, default=0)
    sheet.add_argument("--force", action="store_true")
    judge = sub.add_parser("judge", help="grade the picked turns with the gpt-4o judge, both formats")
    judge.add_argument("--answers", required=True)
    judge.add_argument("--dir", required=True)
    judge.add_argument("--label", required=True)
    agree = sub.add_parser("agree", help="compare the judge with the hand grades")
    agree.add_argument("--dir", required=True)
    agree.add_argument("--label", required=True)
    agree.add_argument("--half", choices=["tune", "report"], required=True)
    args = parser.parse_args()
    {"sheet": cmd_sheet, "judge": cmd_judge, "agree": cmd_agree}[args.command](args)


if __name__ == "__main__":
    main()
