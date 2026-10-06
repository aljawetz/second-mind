"""End-to-end dry run of the alpha system (Sprint 6): the real backend, real
Canvas, the real model, driven over the same HTTP calls the app makes.

    uv run python scripts/e2e_dry_run.py --course 56350 --out e2e-results.json

What it does, in order: list courses, sync the course, ask a covered and an
uncovered question, ask for a grade, list and explain an assignment, record a
lecture (synthetic speech, made with macOS `say`), ask about the recording,
record silence and a file that isn't audio, make a quiz from one week's
sources plus the recording, make flashcards, press Explain, and try invalid
study requests. Every response is saved to --out, with timings.

It never touches the student's real data: it copies ~/.secondmind to a temp
folder and starts its own backend on --port. Run on its own, the backend
reads the Canvas token and model key from the Keychain, so macOS asks for
the login password once (the app itself never does: it passes them in).

macOS only (`say`, `afconvert`). The speech is synthetic, so the word error
rate it reports says nothing about a real classroom recording.
"""

import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

LECTURE = (
    "Good afternoon everyone. Today we continue with literature reviews. Last week we talked about search "
    "criteria, and today I want to focus on how to report your selection process. When you search the "
    "databases, you will find hundreds of papers. You remove duplicates first, then you screen titles and "
    "abstracts, and finally you read the full text of the papers that remain. The PRISMA diagram is a flow "
    "chart that shows how many papers you found, how many you removed at each step, and how many you "
    "included in the end. Every systematic review should include a PRISMA diagram, because it makes your "
    "selection process transparent and repeatable. When you write the inclusion criteria, use the PICO "
    "model: population, intervention, comparison, and outcome. For example, if your population is children "
    "with autism, your intervention is virtual reality training, and your outcome is social skills, then a "
    "paper about adults with depression does not meet your criteria. Group the papers you include by "
    "themes, not one paper at a time. One more thing for your projects. The team check-in for this sprint "
    "moves from Tuesday to Thursday at three p.m., in the same room. Please bring your table of selected "
    "papers to the check-in, with at least ten papers in it. That is all for today."
)


class Run:
    def __init__(self, port: int, course: int, out: Path):
        self.port, self.course, self.out = port, course, out
        self.results: dict = {"course": course, "steps": []}

    def call(self, method, path, body=None, raw=None, timeout=600):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, data)
        res = conn.getresponse()
        text = res.read().decode()
        conn.close()
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) > 1:  # newline-delimited JSON: /ask and /sync stream
            return res.status, [json.loads(line) for line in lines]
        return res.status, json.loads(text) if text.strip() else None

    def step(self, name, fn):
        started = time.time()
        try:
            out, ok = fn(), True
        except Exception as e:  # recorded; the run goes on
            out, ok = {"exception": repr(e)}, False
        seconds = round(time.time() - started, 1)
        self.results["steps"].append({"step": name, "ok": ok, "seconds": seconds, "result": out})
        print(f"[{seconds:6.1f}s] {'OK ' if ok else 'ERR'} {name}", flush=True)
        self.out.write_text(json.dumps(self.results, indent=1, default=str))
        return out

    def ask(self, question):
        status, events = self.call("POST", f"/courses/{self.course}/ask", {"question": question, "course_name": "the course", "history": []})
        if status != 200:
            return {"status": status, "body": events}
        events = events if isinstance(events, list) else [events]
        final = next((e for e in events if "citations" in e), {})
        return {
            "answer": "".join(e.get("delta", "") for e in events),
            "grounded": final.get("grounded"),
            "citations": final.get("citations"),
            "errors": [e["error"] for e in events if "error" in e],
        }

    def wait(self, path, limit):
        started = time.time()
        while time.time() - started < limit:
            _, detail = self.call("GET", path)
            if detail.get("status") in ("done", "error"):
                return detail
            time.sleep(2)
        return {"status": "timeout"}


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref = re.findall(r"[a-z0-9']+", reference.lower())
    hyp = re.findall(r"[a-z0-9']+", hypothesis.lower())
    row = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        prev, row[0] = row[0], i
        for j in range(1, len(hyp) + 1):
            cur = row[j]
            row[j] = min(row[j] + 1, row[j - 1] + 1, prev + (ref[i - 1] != hyp[j - 1]))
            prev = cur
    return round(row[len(hyp)] / max(len(ref), 1), 3)


def make_audio(folder: Path) -> None:
    (folder / "lecture.txt").write_text(LECTURE)
    subprocess.run(["say", "-o", str(folder / "lecture.aiff"), "-f", str(folder / "lecture.txt")], check=True)
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(folder / "lecture.aiff"), str(folder / "lecture.m4a")], check=True)
    import wave

    with wave.open(str(folder / "silence.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * 10)
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(folder / "silence.wav"), str(folder / "silence.m4a")], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--course", type=int, required=True, help="a selected course's Canvas id")
    parser.add_argument("--assignment", type=int, help="an assignment to explain (default: the first listed)")
    parser.add_argument("--week", default="Week 02", help="quiz from the sources under this Canvas heading")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--out", type=Path, default=Path("e2e-results.json"))
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="sm-e2e-"))
    shutil.copytree(Path.home() / ".secondmind", work / "home")
    make_audio(work)
    log = open(work / "backend.log", "w")
    backend = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        cwd=BACKEND,
        env={**os.environ, "SM_HOME": str(work / "home"), "SM_PORT": str(args.port)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    run = Run(args.port, args.course, args.out.resolve())
    c = args.course
    try:
        for _ in range(60):
            try:
                if run.call("GET", "/ping")[1].get("source") == "sm-backend":
                    break
            except OSError:
                time.sleep(1)
        else:
            sys.exit(f"backend didn't start; see {work / 'backend.log'}")

        # Accounts and sync (FR1, FR2)
        run.step("list Canvas courses", lambda: (lambda s, b: {"status": s, "course_listed": any(x["id"] == c for x in b.get("courses", []))})(*run.call("GET", "/courses")))
        run.step("key check: malformed model key", lambda: run.call("POST", "/credentials/validate", {"kind": "openai", "value": "not-a-key"})[1])
        run.step("key check: well-formed but fake model key", lambda: run.call("POST", "/credentials/validate", {"kind": "openai", "value": "sk-" + "x" * 40})[1])

        def sync():
            status, events = run.call("POST", f"/courses/{c}/sync")
            events = events if isinstance(events, list) else [events]
            return {"status": status, "done": next((e for e in events if e.get("done")), None), "items": [e for e in events if not e.get("done")]}

        run.step("sync the course", sync)
        sources = run.step("sources by Canvas heading", lambda: run.call("GET", f"/courses/{c}/study/sources")[1]["sources"])

        # Grounded Q&A (FR3, FR4, FR7)
        run.step("ask: covered", lambda: run.ask("How should we choose which papers to include in a literature review?"))
        run.step("ask: not covered", lambda: run.ask("What does the course say about quantum error correction?"))
        run.step("ask: my grade", lambda: run.ask("What grade did I get on my last assignment?"))

        # Assignment explainer (FR7, FR8)
        assignments = run.step("list assignments (live from Canvas)", lambda: run.call("GET", f"/courses/{c}/assignments")[1]["assignments"])
        target = args.assignment or (assignments[0]["id"] if assignments else None)
        if target:
            run.step(f"explain assignment {target}", lambda: run.call("POST", f"/courses/{c}/assignments/{target}/explain", {})[1])

        # Session capture (FR5)
        def record(audio: bytes, notes=None):
            sid = run.call("POST", f"/courses/{c}/sessions/start")[1]["session_id"]
            if notes:
                run.call("POST", f"/sessions/{sid}/notes", {"text": notes})
            started = time.time()
            stop_status, _ = run.call("POST", f"/sessions/{sid}/stop", raw=audio)
            detail = run.wait(f"/courses/{c}/sessions/{sid}", 600)
            return {"session_id": sid, "stop_status": stop_status, "processing_seconds": round(time.time() - started, 1), **detail}

        lecture = run.step("record a lecture and transcribe it", lambda: record((work / "lecture.m4a").read_bytes(), "My notes: PRISMA, check-in moved."))
        if lecture.get("transcript"):
            run.results["word_error_rate"] = word_error_rate(LECTURE, lecture["transcript"])
            print("word error rate", run.results["word_error_rate"])
        run.step("ask about the recording", lambda: run.ask("When did the professor say the team check-in moves to, and what is the PRISMA diagram for?"))
        run.step("record silence", lambda: record((work / "silence.m4a").read_bytes()))
        run.step("upload a file that isn't audio", lambda: record(b"not audio at all"))

        # Study artifacts (FR9)
        def make(kind, **options):
            status, started = run.call("POST", f"/courses/{c}/study", {"kind": kind, **options})
            if status != 202:
                return {"status": status, "body": started}
            t = time.time()
            detail = run.wait(f"/courses/{c}/study/{started['id']}", 300)
            return {**detail, "seconds": round(time.time() - t, 1)}

        week = [s["item_id"] for s in sources or [] if s["group"].startswith(args.week) and not s["unavailable"]]
        session_id = (lecture or {}).get("session_id")
        quiz = run.step(
            f"quiz from {args.week} and the recording",
            lambda: make("quiz", topic="literature reviews and PRISMA", item_ids=week + ([session_id] if session_id else [])),
        )
        run.step("flashcards from the whole course", lambda: make("flashcards"))

        def explain():
            q = quiz["items"][0]
            right = next(o["text"] for o in q["options"] if o["correct"])
            return run.ask(f'Explain this quiz question: "{q["question"]}" The correct answer is "{right}".')

        run.step("Explain on a quiz question", explain)
        run.step("invalid study requests", lambda: [run.call("POST", f"/courses/{c}/study", b)[0] for b in ({"kind": "essay"}, {"kind": "quiz", "difficulty": "brutal"})])
        print(f"done: {args.out}")
    finally:
        backend.terminate()
        backend.wait(10)
        log.close()


if __name__ == "__main__":
    main()
