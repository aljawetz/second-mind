"""Smoke test for agent memory with the real model, through the real /ask
handler (docs/superpowers/specs/2026-09-25-agent-memory-design.md).

Tells Second Mind a few things about a student across two chats, then
checks in new chats that it remembers them, uses them only when related,
never stores a grade, updates a changed fact and really forgets.

Not a pytest test: makes real, billed calls (a few cents) with the key the
app stored in the Keychain. Runs against a temporary ~/.secondmind, so the
student's own chats and memories are never touched; the real course index
for COURSE is linked in and only searched. Run from backend/:

    uv run python3 scripts/memory_smoke_test.py

Runs so far (2026-10-06):
- "What was it before?" gets a made-up old project: the model doesn't ask
  memory for history. Not fixed yet.
- One run kept a grade in a chat summary ("receiving a 72 on the
  midterm"); the grades filter now catches that phrasing.
"""

import http.client
import json
import re
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config  # noqa: E402
import main  # noqa: E402

COURSE = 55016
NAME = "18-658 Software Requirements and Interaction Design"

home = Path(tempfile.mkdtemp(prefix="sm-memcheck-"))
(home / "index.lancedb").symlink_to(Path.home() / ".secondmind" / "index.lancedb")
config.write_config(home, {"selected_courses": [COURSE]})
main.SM_HOME = home
server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
PORT = server.server_address[1]


def call(method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=180)
    conn.request(method, path, json.dumps(body) if body is not None else None)
    res = conn.getresponse()
    raw = res.read().decode()
    return res.status, raw


def ask(question, cid=None):
    body = {"question": question, "course_name": NAME, **({"conversation_id": cid} if cid else {})}
    status, raw = call("POST", f"/courses/{COURSE}/ask", body)
    assert status == 200, raw
    events = [json.loads(l) for l in raw.splitlines() if l.strip()]
    if any("error" in e for e in events):
        raise RuntimeError([e for e in events if "error" in e])
    answer = "".join(e.get("delta", "") for e in events)
    final = next(e for e in events if "citations" in e)
    assert main.MEMORY_WORKER.wait_idle(300), "memory worker stuck"
    return events[0]["conversation_id"], answer, [m["text"] for m in final.get("memories_used", [])]


def memories(include_inactive=False):
    q = "?include_inactive=1" if include_inactive else ""
    return json.loads(call("GET", f"/courses/{COURSE}/memories{q}")[1])["memories"]


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def show(label, question, answer, used):
    print(f"\n[{label}] Q: {question}\n    used: {used}\n    A: {answer[:300].strip()!r}")


print(f"temp home: {home}\n\n== Telling it things (two chats) ==")
a, _, _ = ask("I'm on team 4 with Priya and Ken, and our innovation project is a smart parking app.")
ask("Please always give me code examples in Java, I don't know Python.", a)
b, _, _ = ask("I finished Task 1 of the innovation project, but I'm stuck on the Task 2 storyboard.")
ask("By the way, I got a 72 on the midterm.", b)
for m in memories():
    print(f"  stored [{m['kind']}] {m['text']}")
facts = " ".join(m["text"] for m in memories() if m["kind"] != "summary").lower()
check("team stored", "team 4" in facts)
check("project stored", "parking" in facts)
check("Java preference stored", "java" in facts)
check("task progress stored", "storyboard" in facts or "task 2" in facts)
check("grade NOT stored (any memory)", not re.search(r"\b72\b", " ".join(m["text"] for m in memories(True))))

print("\n== New chat: should it remember? ==")
probes = [
    ("Which team am I on and what's our project?", lambda ans, used: "4" in ans and "parking" in ans.lower() and used, "recalls team + project"),
    ("Show me a quick example of a unit test.", lambda ans, used: re.search(r"@Test|public (void|class)|assertEquals", ans), "example is in Java"),
    ("Where did I leave off on the innovation project?", lambda ans, used: "storyboard" in ans.lower() or "task 2" in ans.lower(), "recalls where they left off"),
    ("What is a user story?", lambda ans, used: not used, "unrelated: no memories used"),
    ("When is the final exam?", lambda ans, used: not used, "unrelated: no memories used"),
]
for q, ok, name in probes:
    _, ans, used = ask(q)
    show(name, q, ans, used)
    check(name, ok(ans, used))

print("\n== Changing a fact ==")
c, _, _ = ask("Actually our team switched projects, we're now building a campus food delivery app.")
_, ans, used = ask("What is our innovation project now, and what was it before?")
show("update", "What is our innovation project now, and what was it before?", ans, used)
current = " ".join(m["text"] for m in memories() if m["kind"] != "summary").lower()
check("new project is current", "food delivery" in current)
check("old project no longer current", "parking" not in current, "superseded, kept for history")
check("answer gives the new project", "food" in ans.lower())
check("answer gives the old project", "parking" in ans.lower(), "needs recall_memory with include_history")

print("\n== Forgetting ==")
_, ans, used = ask("Please forget that I'm on team 4.")
show("forget", "Please forget that I'm on team 4.", ans, used)
left = " ".join(m["text"] for m in memories(True)).lower()
check("team fact deleted (including summaries)", "team 4" not in left, left[:200] if "team 4" in left else "")

print(f"\n== {sum(ok for _, ok in results)}/{len(results)} checks passed ==")
server.shutdown()
sys.exit(0 if all(ok for _, ok in results) else 1)
