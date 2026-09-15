# Sprint 3 Feasibility PoC Implementation Plan

> **HISTORICAL (2026-09-14).** This plan drove the Sprint 3 feasibility work and is kept as the
> record of it. Two things diverged from the plan in execution: Onyx was installed in **Standard**
> mode rather than Lite, and Canvas integration was built as a **native Onyx connector**
> (`onyx-patch/connector.py`, 1,068 lines) rather than through the MCP data-source route described
> in Task 2.
>
> Outcome: **Modify** — RAG over real Canvas content is validated, the Onyx substrate is not. See
> [§10.1 of the SSB spec](../specs/2026-09-14-ssb-design.md) for the reasoning. Do not execute the
> remaining tasks in this plan; they target the Onyx architecture.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove or disprove, on one real CMU course, that a self-hosted Onyx instance fed
through the existing `canvas-api` MCP server can produce cited, Socratically-behaved tutor
answers good enough to justify continuing this project design — per spec section 6.

**Architecture:** Stand up Onyx locally (Lite mode), connect it to the already-working local
`canvas-mcp-server` process as an MCP data source/action, index one real course, configure a
Socratic system prompt on top of it, then run and hand-grade a fixed set of real student
questions against it through a small Python evaluation harness.

**Tech Stack:** Onyx (self-hosted, `onyx-cli`), the existing `canvas-mcp-server` (Python, already
installed at `~/mcp-servers/canvas-mcp`), Python 3.11+ for the eval harness, `pytest`,
`requests`, `pyyaml`.

**Spec:** `docs/superpowers/specs/2026-09-11-canvas-ai-tutor-design.md`

## Global Constraints

- Solo-executable: this plan assumes one person, not a staffed team — no task requires parallel
  work.
- Scope is the Sprint 3 PoC only (spec §6): one course, one local Onyx instance, hand-graded
  evaluation. Do not build multi-course indexing, multi-user auth, or a custom frontend in this
  plan — those are explicitly out of scope per spec §3/§9 until the PoC result justifies them.
- Never commit the Canvas API token or any other secret to git. It lives in `.env` at the repo
  root, which must be gitignored before it is ever created.
- Every claim the tutor makes in the eval must be checked against an explicit expected source in
  `eval/questions.yaml` — "it sounded right" is not a passing grade (spec §6, §9).

---

### Task 1: Stand up Onyx locally and smoke-test it with no data source

**Files:**
- Create: `onyx-setup/NOTES.md`
- Create: `.gitignore`

**Interfaces:**
- Produces: a running local Onyx instance reachable in a browser, and a record in
  `onyx-setup/NOTES.md` of exactly how it was installed (command used, mode chosen, any prompts
  answered) so Task 2 doesn't have to rediscover this.

- [ ] **Step 1: Create `.gitignore` before anything else exists to gitignore**

```
.env
.venv/
__pycache__/
*.pyc
onyx-data/
```

- [ ] **Step 2: Commit the `.gitignore`**

```bash
cd /Users/arthurjawetz/Code/CMU/canvas-ai-tutor
git add .gitignore
git commit -m "chore: add gitignore before any local secrets/venvs exist"
```

- [ ] **Step 3: Install Onyx**

Run:
```bash
curl -fsSL https://onyx.app/install_onyx.sh | bash
```
If prompted, choose **Lite** mode (single-machine, meant for exactly this kind of local
proof-of-concept — Standard mode assumes a multi-node production deployment you don't need yet).

If the install script fails or is no longer at that URL, fall back to:
```bash
uv tool install onyx-cli && onyx-cli deploy install
```
(`uv` must be installed first: `curl -LsSf https://astral.sh/uv/install.sh | sh`)

- [ ] **Step 4: Record what actually happened**

Write into `onyx-setup/NOTES.md`:
- Which install method worked
- Which mode was chosen (Lite/Standard)
- The URL and port Onyx is now reachable on (e.g. `http://localhost:3000`)
- Any environment variables the installer asked for and where you put them

- [ ] **Step 5: Verify it actually works with zero data connected**

Open the Onyx URL from Step 4 in a browser, create an admin account if prompted, configure at
least one LLM provider (Anthropic or OpenAI API key, entered into Onyx's own admin settings UI —
not into any file in this repo), and send it one throwaway chat message with no documents
indexed yet.

Expected: you get a plain LLM response back with no citations (there's nothing indexed yet). If
you get an error instead, do not proceed to Task 2 — fix the base install first and update
`onyx-setup/NOTES.md` with what was wrong.

- [ ] **Step 6: Commit the setup notes**

```bash
git add onyx-setup/NOTES.md
git commit -m "docs: record local Onyx install steps"
```

---

### Task 2: Connect the existing canvas-mcp-server to Onyx as a data source

**Files:**
- Modify: `onyx-setup/NOTES.md`
- Create: `.env` (gitignored — never committed)
- Create: `.env.example`

**Interfaces:**
- Consumes: the running Onyx instance from Task 1; the existing local MCP server binary at
  `~/mcp-servers/canvas-mcp/.venv/bin/canvas-mcp-server` (already configured and working — you
  used it earlier this session against `canvas.cmu.edu`).
- Produces: a record in `onyx-setup/NOTES.md` of whether Onyx can consume a local stdio MCP
  server directly, or needs a bridge — this is the single riskiest unknown in the whole PoC and
  everything after this task depends on the answer.

- [ ] **Step 1: Write `.env.example` (safe to commit — no real values)**

```
CANVAS_API_TOKEN=your_canvas_token_here
CANVAS_API_URL=https://canvas.cmu.edu/api/v1
```

- [ ] **Step 2: Write your real `.env` (never committed — already gitignored from Task 1)**

```
CANVAS_API_TOKEN=<copy the value from ~/.cursor/mcp.json's canvas-api entry>
CANVAS_API_URL=https://canvas.cmu.edu/api/v1
```

- [ ] **Step 3: Commit only the example file**

```bash
git add .env.example
git commit -m "docs: add .env.example for canvas credentials"
git status
```
Expected: `git status` shows `.env` as untracked (or not shown at all if gitignore is working) —
confirm this before moving on. If `.env` shows as staged or tracked, stop and fix `.gitignore`.

- [ ] **Step 4: Attempt to add the MCP server as a data source in Onyx's admin UI**

In Onyx, go to the admin/connectors section and look for an option to add an MCP-based
action/connector. Try pointing it at the local server using the same launch command already
proven to work (`/Users/arthurjawetz/mcp-servers/canvas-mcp/.venv/bin/canvas-mcp-server`, no
args, with `CANVAS_API_TOKEN` and `CANVAS_API_URL` from your `.env` passed through as
environment variables).

- [ ] **Step 5: Record the result**

Append to `onyx-setup/NOTES.md` one of these two outcomes:

- **If it connects**: note the exact UI fields you filled in, so this is reproducible.
- **If Onyx only accepts remote/HTTP MCP servers (not local stdio processes)**: this is a real,
  known gap for locally-run MCP servers. Install a stdio-to-HTTP bridge and point Onyx at that
  instead:
  ```bash
  uvx mcp-proxy --port 8100 -- /Users/arthurjawetz/mcp-servers/canvas-mcp/.venv/bin/canvas-mcp-server
  ```
  Then add `http://localhost:8100` as the MCP source in Onyx instead of the raw binary. Record
  in `onyx-setup/NOTES.md` that the bridge was necessary and the exact command used, since this
  is exactly the kind of finding that belongs in the Sprint 3 report either way.

- [ ] **Step 6: Confirm the connection is live**

In Onyx's admin UI, confirm the new MCP source shows as connected/healthy, not just "added."

- [ ] **Step 7: Commit the notes update**

```bash
git add onyx-setup/NOTES.md
git commit -m "docs: record MCP connector setup outcome (direct or via bridge)"
```

---

### Task 3: Index one real course into Onyx

**Files:**
- Modify: `onyx-setup/NOTES.md`

**Interfaces:**
- Consumes: the working MCP connection from Task 2.
- Produces: one Onyx index/"space" populated with a real course's syllabus, pages, and files —
  the actual data the eval in Task 5–8 will run against.

- [ ] **Step 1: Pick the pilot course**

Use course 56350 (49797, "Advanced AI for Industry and Society") — you already have full read
access to it via the MCP server and know its structure (7 modules, syllabus, pages, files).

- [ ] **Step 2: Trigger indexing in Onyx**

Using the MCP connection from Task 2, pull in: the syllabus, all published pages (e.g.
`nvidia-building-rag-agents-with-llms`, `ai-research-assistance-explained`,
`braineeg-research-project`), and at least the files you already know are problematic —
specifically `CatherineFang_Bio.pdf`, since it's the known image-heavy PDF from spec §5. Do not
skip it: it's your test case for the exact risk this PoC exists to check.

- [ ] **Step 3: Verify what actually got indexed**

In Onyx's admin/document view for this index, check: is `CatherineFang_Bio.pdf` present at all?
If present, does it show as text you can search on, or as an opaque unindexed file? Record both
the pass and the fail case in `onyx-setup/NOTES.md` — a fail here is a legitimate, useful Sprint
3 finding per spec §6, not a blocker to fix before reporting.

- [ ] **Step 4: Commit the notes update**

```bash
git add onyx-setup/NOTES.md
git commit -m "docs: record course indexing results, including known image-PDF case"
```

---

### Task 4: Configure the Socratic tutor persona and manually smoke-test it

**Files:**
- Create: `prompts/socratic_tutor_system_prompt.md`
- Modify: `onyx-setup/NOTES.md`

**Interfaces:**
- Consumes: the indexed course from Task 3.
- Produces: `prompts/socratic_tutor_system_prompt.md` — the exact system prompt text configured
  in Onyx, kept in the repo so it's versioned and reviewable, not buried only in Onyx's own
  settings UI.

- [ ] **Step 1: Write the system prompt to a file first**

```markdown
# Socratic Tutor System Prompt

You are a study tutor for one specific CMU course. You may only use the indexed course
material (syllabus, pages, files) to answer questions. If the indexed material does not
contain enough information to answer, say so explicitly instead of using outside knowledge.

Default behavior: do not give the direct answer immediately. Ask a guiding question or give a
hint that points the student toward the relevant concept, using only the indexed material.

Escape hatch: if the student says "just tell me", "give me the answer", or has already asked
about the same topic more than twice in this conversation, give the direct answer plainly,
still citing the specific page or file it came from.

Every factual claim must be traceable to a specific cited source from the index. Never
present an unsupported claim as fact.
```

- [ ] **Step 2: Paste this exact text into Onyx's assistant/persona configuration**

Scope the assistant to the course index created in Task 3 (not to Onyx's whole document store —
this is what makes it course-specific rather than a general RAG chatbot per spec §3).

- [ ] **Step 3: Manually smoke-test with 3 real questions**

Ask, in Onyx's chat UI:
1. A factual question clearly answerable from a page you indexed.
2. The same question rephrased as "just tell me the answer" — confirm the escape hatch fires.
3. A question about something NOT in the indexed course at all (e.g. an unrelated topic) —
   confirm it says it doesn't know rather than answering from general knowledge.

- [ ] **Step 4: Record pass/fail for each of the 3 smoke tests**

Append the results to `onyx-setup/NOTES.md`. If any of the 3 fail, revise the prompt in
`prompts/socratic_tutor_system_prompt.md`, re-paste it into Onyx, and re-test before moving on —
this behavior is the product's core differentiator per spec §4/§8, so it's worth getting right
before running the full eval set.

- [ ] **Step 5: Commit**

```bash
git add prompts/socratic_tutor_system_prompt.md onyx-setup/NOTES.md
git commit -m "feat: add Socratic tutor system prompt, smoke-tested against 3 cases"
```

---

### Task 5: Write the hand-crafted evaluation question set

**Files:**
- Create: `eval/questions.yaml`
- Create: `eval/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `eval/questions.yaml` (list of question records) and `eval/schema.py`'s
  `load_questions(path: str) -> list[Question]`, which Task 7's `run_eval.py` will import.
- `Question` fields: `id: str`, `text: str`, `expected_source: str` (a page URL slug or filename
  you know the answer should cite), `topic: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema.py
from eval.schema import load_questions, Question

def test_load_questions_returns_question_objects():
    questions = load_questions("eval/questions.yaml")
    assert len(questions) >= 15
    first = questions[0]
    assert isinstance(first, Question)
    assert first.id
    assert first.text
    assert first.expected_source
    assert first.topic

def test_load_questions_rejects_missing_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_questions("eval/does_not_exist.yaml")
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
cd /Users/arthurjawetz/Code/CMU/canvas-ai-tutor
python3 -m pytest tests/test_schema.py -v
```
Expected: FAIL — `eval/schema.py` doesn't exist yet.

- [ ] **Step 3: Write `eval/schema.py`**

```python
# eval/schema.py
from dataclasses import dataclass
import yaml


@dataclass
class Question:
    id: str
    text: str
    expected_source: str
    topic: str


def load_questions(path: str) -> list[Question]:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    return [Question(**item) for item in raw["questions"]]
```

- [ ] **Step 4: Write `eval/questions.yaml` with 15-20 real questions about course 56350**

Base these on the actual module content you already pulled this session (Week 1-3 pages, the
RAG agents page, AI Research Assistance page, syllabus). Example structure — replace with real
questions once you've read through the actual page content for each topic:

```yaml
questions:
  - id: q01
    text: "What does the course say a RAG agent needs in order to ground its answers in real documents instead of hallucinating?"
    expected_source: "nvidia-building-rag-agents-with-llms"
    topic: "RAG agents"
  - id: q02
    text: "According to the course, what's the difference between the AI Research Assistance tools covered in Week 3 and just using a general chatbot?"
    expected_source: "ai-research-assistance-explained"
    topic: "AI research assistance"
  - id: q03
    text: "What are the three findings reported so far in the BrainEEG research project, and which one is described as the most surprising?"
    expected_source: "braineeg-research-project"
    topic: "BrainEEG research"
```
Continue this pattern until you have at least 15 questions covering every indexed page/file,
including at least 2 questions specifically targeting content from `CatherineFang_Bio.pdf` —
these are your canary for whether the image-PDF ingestion problem from Task 3 actually matters
in practice.

- [ ] **Step 5: Run the test again to confirm it passes**

```bash
python3 -m pytest tests/test_schema.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add eval/questions.yaml eval/schema.py tests/test_schema.py
git commit -m "test: add eval question set and schema loader"
```

---

### Task 6: Discover Onyx's chat API contract and implement `eval/onyx_client.py`

**Files:**
- Create: `eval/onyx_client.py`
- Test: `tests/test_onyx_client.py`
- Modify: `onyx-setup/NOTES.md`

**Interfaces:**
- Produces: `ask(question: str, base_url: str, api_key: str) -> AnswerResult`, where
  `AnswerResult` has fields `answer_text: str` and `cited_sources: list[str]`.
- Consumes: Onyx's real chat API, whose exact request/response shape is not yet known and must
  be discovered in Step 1 below before the client can be written for real.

- [ ] **Step 1: Discover the real API contract**

With Onyx running locally (from Task 1) and the assistant configured (Task 4), open your
browser's DevTools Network tab, ask the tutor one question through the normal chat UI, and find
the actual HTTP request Onyx's frontend sends (method, path, headers/auth, JSON body) and the
actual response shape (where the answer text and cited document references live in the JSON).

Write what you found into `onyx-setup/NOTES.md` under a new "Chat API contract" section,
including a real example request and response pair (redact any API key value before writing it
down).

- [ ] **Step 2: Write the failing test against the discovered contract**

Replace the example JSON below with the actual shape you recorded in Step 1 — this is a
template, not a guess to leave as-is:

```python
# tests/test_onyx_client.py
from unittest.mock import patch, MagicMock
from eval.onyx_client import ask


@patch("eval.onyx_client.requests.post")
def test_ask_parses_answer_and_citations(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "answer": "The course describes RAG as grounding an LLM in retrieved documents.",
        "citations": [{"document_id": "nvidia-building-rag-agents-with-llms"}],
    }
    mock_post.return_value = mock_response

    result = ask("What is RAG?", base_url="http://localhost:3000", api_key="fake-key")

    assert "RAG" in result.answer_text
    assert "nvidia-building-rag-agents-with-llms" in result.cited_sources
```

- [ ] **Step 3: Run it to confirm it fails**

```bash
python3 -m pytest tests/test_onyx_client.py -v
```
Expected: FAIL — `eval/onyx_client.py` doesn't exist yet.

- [ ] **Step 4: Implement `eval/onyx_client.py` against the real, discovered contract**

Adjust the endpoint path, auth header, and JSON field names below to match exactly what you
recorded in Step 1 — do not guess if what you wrote down differs from this skeleton:

```python
# eval/onyx_client.py
from dataclasses import dataclass
import requests


@dataclass
class AnswerResult:
    answer_text: str
    cited_sources: list[str]


def ask(question: str, base_url: str, api_key: str) -> AnswerResult:
    response = requests.post(
        f"{base_url}/api/chat/send-message",  # replace with the real path from Step 1
        headers={"Authorization": f"Bearer {api_key}"},
        json={"message": question},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return AnswerResult(
        answer_text=data["answer"],
        cited_sources=[c["document_id"] for c in data.get("citations", [])],
    )
```

- [ ] **Step 5: Run the test again to confirm it passes**

```bash
python3 -m pytest tests/test_onyx_client.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add eval/onyx_client.py tests/test_onyx_client.py onyx-setup/NOTES.md
git commit -m "feat: add Onyx chat API client based on discovered contract"
```

---

### Task 7: Implement the eval runner

**Files:**
- Create: `eval/run_eval.py`
- Test: `tests/test_run_eval.py`

**Interfaces:**
- Consumes: `load_questions` from `eval/schema.py` (Task 5), `ask` from `eval/onyx_client.py`
  (Task 6).
- Produces: `run_eval(questions_path: str, base_url: str, api_key: str, output_path: str) -> None`,
  which writes one JSON line per question to `output_path` with fields `id`, `text`,
  `expected_source`, `answer_text`, `cited_sources`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_run_eval.py
import json
from unittest.mock import patch
from eval.run_eval import run_eval


@patch("eval.run_eval.ask")
def test_run_eval_writes_one_json_line_per_question(mock_ask, tmp_path):
    from eval.onyx_client import AnswerResult
    mock_ask.return_value = AnswerResult(
        answer_text="mock answer", cited_sources=["some-page"]
    )

    questions_file = tmp_path / "questions.yaml"
    questions_file.write_text(
        "questions:\n"
        "  - id: q01\n"
        "    text: 'What is RAG?'\n"
        "    expected_source: 'nvidia-building-rag-agents-with-llms'\n"
        "    topic: 'RAG'\n"
    )
    output_file = tmp_path / "results.jsonl"

    run_eval(
        questions_path=str(questions_file),
        base_url="http://localhost:3000",
        api_key="fake-key",
        output_path=str(output_file),
    )

    lines = output_file.read_text().strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["id"] == "q01"
    assert record["answer_text"] == "mock answer"
    assert record["cited_sources"] == ["some-page"]
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
python3 -m pytest tests/test_run_eval.py -v
```
Expected: FAIL — `eval/run_eval.py` doesn't exist yet.

- [ ] **Step 3: Implement `eval/run_eval.py`**

```python
# eval/run_eval.py
import json
from eval.schema import load_questions
from eval.onyx_client import ask


def run_eval(questions_path: str, base_url: str, api_key: str, output_path: str) -> None:
    questions = load_questions(questions_path)
    with open(output_path, "w") as out:
        for q in questions:
            result = ask(q.text, base_url=base_url, api_key=api_key)
            record = {
                "id": q.id,
                "text": q.text,
                "expected_source": q.expected_source,
                "answer_text": result.answer_text,
                "cited_sources": result.cited_sources,
            }
            out.write(json.dumps(record) + "\n")


if __name__ == "__main__":
    import os
    run_eval(
        questions_path="eval/questions.yaml",
        base_url=os.environ.get("ONYX_BASE_URL", "http://localhost:3000"),
        api_key=os.environ["ONYX_API_KEY"],
        output_path="eval/results/run1.jsonl",
    )
```

- [ ] **Step 4: Run the test again to confirm it passes**

```bash
python3 -m pytest tests/test_run_eval.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
mkdir -p eval/results
git add eval/run_eval.py tests/test_run_eval.py
git commit -m "feat: add eval runner that scores questions against live Onyx instance"
```

---

### Task 8: Run the real evaluation and write the Proceed/Modify/Pivot decision

**Files:**
- Create: `eval/results/run1.jsonl` (generated, not hand-written)
- Create: `eval/results/2026-09-XX-decision.md`

**Interfaces:**
- Consumes: `run_eval.py` from Task 7, run against the real local Onyx instance from Tasks 1-4.
- Produces: the actual Sprint 3 deliverable — a graded result set and a written decision, per
  spec §6.

- [ ] **Step 1: Add your real Onyx API key to `.env`**

```
ONYX_API_KEY=<the key you generated in Onyx's admin UI in Task 1>
```

- [ ] **Step 2: Run the eval for real**

```bash
cd /Users/arthurjawetz/Code/CMU/canvas-ai-tutor
export $(cat .env | xargs)
python3 -m eval.run_eval
```
Expected: `eval/results/run1.jsonl` now has one line per question in `eval/questions.yaml`.

- [ ] **Step 3: Hand-grade every line**

Open `eval/results/run1.jsonl` next to `eval/questions.yaml` and, for each question, grade by
hand against these four checks from spec §6:
1. Was the right source retrieved? (compare `cited_sources` to `expected_source`)
2. Does the citation actually support the answer text, or is it a mismatch/hallucination?
3. Did the Socratic behavior show up appropriately, or did it just answer directly? (re-run
   flagged questions manually in the Onyx chat UI if the JSON alone doesn't make this clear)
4. For the `CatherineFang_Bio.pdf` questions specifically: did the answer show any real content
   from that file, or did it fail silently?

- [ ] **Step 4: Write the decision doc**

Create `eval/results/2026-09-XX-decision.md` (use the actual date you ran this) with:
- A results table: question id, pass/fail on each of the 4 checks above.
- Overall citation-groundedness rate (spec §7's technical metric): `(questions passing check 1
  and 2) / (total questions)`.
- Retrieval precision@1 (spec §7's other technical metric): since each question in
  `eval/questions.yaml` has exactly one `expected_source`, this is `(questions where the first
  cited_sources entry equals expected_source) / (total questions)` — read straight off the same
  `run1.jsonl` data used for check 1.
- An explicit **Proceed / Modify / Pivot** call per spec §6, with the reasoning. If the image-PDF
  questions failed, that alone does not mean Pivot — per spec §6 that's a legitimate Modify
  (scope MVP to text-based course content, treat slide-deck OCR as a later stretch goal).

- [ ] **Step 5: Commit the real results and the decision**

```bash
git add eval/results/
git commit -m "docs: Sprint 3 PoC results and Proceed/Modify/Pivot decision"
git push
```
