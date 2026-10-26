"""Sprint 8 robustness measurements on the real index (search only, no API
key). Two checks:

  noise  the same answerable questions typed badly, scored with the fact
         labels, next to the clean versions. A robust search loses little.
  load   many searches at once: errors and latency percentiles.

    uv run python3 scripts/robustness_eval.py --index ~/second-mind-eval-index-2026-10-26 --out PATH
"""

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ask_modes_eval as ev  # noqa: E402
import indexing  # noqa: E402

SEED = 8


def typos(q: str, rng: random.Random) -> str:
    """Swap two neighbouring letters in about one word in four (words of 4+ letters)."""
    out = []
    for w in q.split(" "):
        if len(w) >= 4 and rng.random() < 0.25:
            i = rng.randrange(1, len(w) - 2)
            w = w[:i] + w[i + 1] + w[i] + w[i + 2 :]
        out.append(w)
    return " ".join(out)


PERTURBATIONS = {
    "clean": lambda q, rng: q,
    "typos": typos,
    "ALL CAPS, no punctuation": lambda q, rng: "".join(c for c in q.upper() if c.isalnum() or c == " "),
    "filler words": lambda q, rng: "um hey so quick question " + q.lower() + " thanks",
    "cut off at 60%": lambda q, rng: " ".join(q.split()[: max(2, int(len(q.split()) * 0.6))]),
    "extra spaces and newlines": lambda q, rng: "  " + q.replace(" ", " \n ", 2).replace(" ", "   ", 2) + "  ",
}


def single_answerable(cases: list[dict]) -> list[dict]:
    return [c for c in cases if c.get("gold_facts") and len(c["turns"]) == 1]


def noise(index_for, cases):
    results = {}
    for name, perturb in PERTURBATIONS.items():
        rng = random.Random(SEED)
        perturbed = []
        for c in cases:
            d = dict(c)
            d["turns"] = [perturb(c["turns"][0], rng)]
            perturbed.append(d)
        scored = ev.evaluate_retrieval(perturbed, index_for)
        fl = scored["metrics"]["fact_labels"]
        results[name] = {"hits": fl["hits"], "n": fl["n"], "top1_hits": fl["top1_hits"], "mrr": round(fl["mrr"], 3)}
    return results


def load(index_for, cases, workers=8, repeats=5):
    queries = [c["turns"][0] for c in cases] * repeats
    retriever = ev.shipped_retriever(index_for(cases[0].get("course", ev.DEFAULT_COURSE)))
    errors = []

    def one(q):
        t = time.perf_counter()
        try:
            retriever.retrieve(q)
        except Exception as e:  # noqa: BLE001 - counted, not hidden
            errors.append(repr(e))
        return time.perf_counter() - t

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        times = sorted(pool.map(one, queries))
    wall = time.perf_counter() - start
    return {
        "searches": len(queries),
        "workers": workers,
        "errors": len(errors),
        "error_samples": errors[:3],
        "p50_s": round(statistics.median(times), 3),
        "p95_s": round(times[int(len(times) * 0.95) - 1], 3),
        "max_s": round(times[-1], 3),
        "throughput_per_s": round(len(queries) / wall, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    db_path = Path(args.index).expanduser()

    def index_for(course_id):
        return indexing.load_index(db_path, f"course_{course_id}")

    cases = single_answerable(ev.cases_for("sprint8") + ev.cases_for("sprint8-test"))
    report = {"questions": len(cases), "seed": SEED, "noise": noise(index_for, cases), "load": load(index_for, cases)}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(f"{len(cases)} answerable single-turn questions")
    for name, r in report["noise"].items():
        print(f"{name:28s} facts found {r['hits']}/{r['n']}  right chunk first {r['top1_hits']}  mrr {r['mrr']}")
    print("load:", report["load"])


if __name__ == "__main__":
    main()
