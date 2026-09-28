# Agent memory evaluation — design

**Status:** draft for team review
**Owner:** Yongjie
**Evaluates:** [agent memory design](2026-09-25-agent-memory-design.md)
**Output:** `docs/evaluations/2026-09-28-agent-memory/` (report, grades, sampled question ids)
**Script:** `backend/scripts/memory_eval.py` (new)

## 1. What the evaluation has to show

This maps to the Sprint 5 rubric: evaluation and baseline comparison (30%), and technical
analysis (20%).

1. Does the memory layer answer memory questions better than what Second Mind does today?
2. Is it better than the two simple alternatives (everything in context; search over raw turns),
   and at what cost?
3. Which parts of the lifecycle earn their place (ablations, P1)?
4. Does course Q&A stay as good as it is now?
5. Does forgetting work: updated facts, explicit forget requests, no grades stored, no leaks
   between courses?

## 2. Why this baseline

Sprint 3's baseline measured text extraction from slides and PDFs, not answering, so it can't be
compared with a memory system. The rubric allows "another appropriate alternative". The main
baseline here is **the shipped chat**, which is Second Mind's own memory today: a 6-turn window
and nothing across chats. Two standard alternatives come from the LongMemEval paper: the whole
history in context, and retrieval over raw turns.

Measuring course search precision@k against Sprint 3 is separate team work and not part of this
spec.

## 3. Systems compared

| Id | System | What it sees when answering |
|---|---|---|
| **S0** | Shipped chat memory (baseline) | The last 6 question/answer pairs of the history, answers cut to 1,500 chars (`chat.HISTORY_TURNS`, `chat.HISTORY_ANSWER_CHARS`) |
| **S1** | Everything in context | Every past session in order, each tagged with its date. Oldest sessions dropped only if the context window is exceeded (count reported) |
| **S2** | Search over raw turns | Each user/assistant pair embedded with the same BGE model; top 10 by cosine, with session dates |
| **S3** | Memory layer | Sessions replayed through `MemoryService.observe_session` at their real dates, a `sweep()` at question time, then the profile block, automatic recall, and up to 2 `recall_memory` calls |
| A1 (P1) | S3 without consolidation | Every candidate is ADDed: no UPDATE, INVALIDATE, or NOOP |
| A2 (P1) | S3 without recency and importance | Score = rank fusion only |
| A3 (P1) | S3 without keyword search | Vector list only |

- Every system uses gpt-4o-mini at temperature 0.1 (chat's current setting) to answer, and S3
  uses it for extraction too.
- A1 needs its own replay, but extraction results are cached (§4.3), so it only adds
  consolidation and answering calls. A2 and A3 reuse S3's stores.

**Two ways of running the systems:**

- **On LongMemEval**, all four answer with the same neutral prompt ("You are a helpful assistant
  with memory of past conversations. Today is {question_date}…"). That tests the memory layer,
  not Second Mind's course-assistant prompt. The prompt is general-domain because the benchmark
  is.
- **On the student-memory set**, S0 and S3 run the real product path, `chat.answer` (with and
  without `memory=`), against a real course index.

## 4. Benchmark 1: LongMemEval

### 4.1 Data

- **Source:** [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned),
  MIT license. This is the authors' cleaned release, which replaces the original.
- **Files used:**
  - `longmemeval_s_cleaned.json` (277 MB): each question has its own history of about 50 dated
    sessions, around 115k tokens.
  - `longmemeval_oracle.json` (15 MB): the same questions, but only the sessions that contain the
    answer.
- **Fields used:**
  - `question_id`, `question_type`, `question`, `answer`, `question_date`
  - `haystack_session_ids`, `haystack_dates`, `haystack_sessions`: lists of
    `{role, content, has_answer}`
  - `answer_session_ids`
  - Questions whose id contains `_abs` are unanswerable ("abstention") questions.
- **Question types:** `single-session-user`, `single-session-assistant`,
  `single-session-preference`, `multi-session`, `temporal-reasoning`, `knowledge-update`.
- **How they map to the lifecycle:**
  - extraction → the single-session types
  - consolidation and superseding → knowledge-update
  - dates and `event_time` → temporal-reasoning
  - recall across chats → multi-session
  - knowing when nothing was said → abstention
- **Download:** the harness fetches both files with `httpx` (already a dependency) from the
  dataset's `resolve/main/` URLs into `backend/.cache/longmemeval/`. That folder gets added to
  `.gitignore` in the same change. No `huggingface_hub` dependency.

### 4.2 Sampling (tuning and reporting on separate questions)

The same discipline as the ask-modes report, which caught a result biased toward the option that
had been tuned:

- **Development set:** 30 questions from the oracle split, 5 per type, used freely for tuning
  prompts and constants.
- **Test set:** 120 questions from the S split, 20 per type, drawn with a fixed seed and
  excluding every development question. At least 10 must be abstention questions; if the draw has
  fewer, abstention questions are swapped in within their type. The ids are committed as
  `sample_ids.json` before any test run.
- **Freezing:** prompts and constants are frozen before the first test run. If they change after
  it, the report says so and reruns every system.

### 4.3 Replaying the history (S3)

- Sessions are fed in date order: `observe_session(turns, at=haystack_date, session_id)`.
- One extraction call per session, not per turn, to keep cost down. The product does one turn per
  call. Same function, different batch size; recorded in §11.
- Extraction output is cached by `(session_id, prompt hash)`. Where a session appears in more than
  one question's history, it's extracted once (how much overlap there is will be measured once
  the data is downloaded). A1 always reuses S3's extractions.
- Each question gets a fresh, empty memory store in a temporary directory. Nothing leaks between
  questions.

### 4.4 Judging

- **Prompts:** the benchmark's own judge prompts, copied with attribution from
  `src/evaluation/evaluate_qa.py` in the LongMemEval repo. There is one prompt per question type
  and a separate one for abstention, and an answer counts as correct if the judge's reply
  contains "yes".
- **Judge model:** gpt-4o, one of the three the script supports and the one the paper reports. It
  is stronger than the model under test.
- **Human check:** Yongjie grades 40 randomly drawn judged answers, blind to which system and
  which judge verdict. The report gives the agreement rate.

### 4.5 Metrics

- **Accuracy:** overall and per question type, with abstention reported separately.
  - S0 will do well on abstention simply by knowing almost nothing. Reporting it separately stops
    that from hiding in the average.
  - The headline number is **accuracy on the answerable questions**.
- **Evidence recall@5.** Whether the retrieved items come from a session in
  `answer_session_ids`.
  - S2: the retrieved turn's session.
  - S3: each recalled memory's `provenance`, which is why provenance is in the schema.
  - For multi-session questions, "any evidence session" and "all evidence sessions" are both
    reported.
- **Cost and speed:**
  - prompt tokens per answer
  - answer latency, median and 95th percentile
  - write cost per session for S3: calls, tokens, and dollars
- **Store size:** memories per question, and the compression ratio (tokens of memory text ÷
  tokens of the raw history).
- **Consolidation activity:** ADD/UPDATE/INVALIDATE/NOOP counts from `ops_log`, compared between
  knowledge-update questions and the rest.

### 4.6 Statistics

- 95% Wilson intervals on every accuracy.
- Paired McNemar tests on the same 120 questions for S3 vs S0 and S3 vs S2.
- With 20 questions per type, per-type differences under about 25 points aren't conclusive, and
  the report says so. Overall (about 110 answerable questions), the interval is about ±9 points.

## 5. Benchmark 2: student-memory set

LongMemEval is general chat. It doesn't test what memory has to do inside Second Mind:
- following a preference in course answers
- picking up an assignment where the student left off
- an explicit "forget that"
- the grades filter
- isolation between courses
- memory and course search working together

### 5.1 Build

- **Timelines:** 12 test timelines plus 3 development timelines, as JSON in
  `backend/scripts/memory_eval_fixtures/`.
- **Each timeline:** a student's 3–6 dated conversations across a simulated semester in 18-654
  (course 55710, already used in the ask-modes evaluation), followed by dated probe questions.
- **Assistant turns during replay** are generated live by the system under test, so extraction
  sees real Second Mind answers, not idealized ones.
- **When they're written:** before any tuning, and not changed after the prompts are frozen.

```json
{
  "id": "T03",
  "course_id": 55710,
  "conversations": [
    {"at": "2026-09-08T18:30:00", "turns": ["I'm on team 4 with Priya and Ken, we picked the recommender project.", "What's the first milestone about?"]},
    {"at": "2026-09-15T20:00:00", "turns": ["We switched to the fraud-detection project, the recommender one was taken."]}
  ],
  "probes": [
    {"at": "2026-09-22T10:00:00", "category": "knowledge_update", "question": "Which project is my team doing?", "expect": "fraud detection", "must_not": "recommender"},
    {"at": "2026-09-22T10:05:00", "category": "temporal", "question": "What project did we have before we switched?", "expect": "recommender"}
  ],
  "store_checks": [{"type": "absent", "pattern": "(?i)\\b\\d{1,3}\\b.*midterm|midterm.*\\b\\d{1,3}\\b"}]
}
```

### 5.2 Probe categories (about 50 probes)

| Category | Example | How it's graded |
|---|---|---|
| Profile recall | "Which team am I on?" | Blind G/O/B |
| Preference followed | Earlier: "use Java, I don't know Python." Later: "Show me a stub example." | Blind: is the example in Java? |
| Task continuity | "Where did I leave off on A3?" | Blind |
| Updated fact / before-after | "Which project is my team doing?" / "…before we switched?" | Blind, with `must_not` |
| Explicit forget | "Forget that I'm auditing." Later: "Am I auditing?" | Blind **and** automatic check that the memory row is gone |
| Memory + course | "Which lecture covers the thing I said I was stuck on last week?" | Blind: needs the memory *and* a correct course citation |
| Filters and isolation | "I got a 72 on the midterm." Later: "What did I get?" Plus two probes asked in a second course | Automatic check that nothing about the grade is stored or recalled, and nothing from course A appears in course B, plus blind grade |
| Never said | A question about something the student never mentioned | Blind: must say it doesn't know |

### 5.3 Grading

Same method as [the ask-modes report](../../evaluations/2026-09-23-ask-modes/report.md):

- Each probe's S0 and S3 answers are shuffled under random letters.
- Grades (Good / OK / Bad) are saved before the letters are matched back to systems.
- If Lakshita (testing and calibration) can grade an overlapping third of the probes, the report
  gives inter-rater agreement.

Raw answers stay out of git, because they quote course material including staff names, the same
reason as last time. Grades are committed.

## 6. Regression: course Q&A must not get worse

- Add mode `M` to `scripts/ask_modes_eval.py`: the shipped chat with memory switched on. Memory
  builds up across cases in order, the way a real student's would.
- Run `--set first` and `--set heldout`, and grade blind against the latest grades in
  `reindexed-grades.json`: 32/34 on the first set, 28/33 held out.
- **Passes if:** at most one fewer Good per set, and no new confidently wrong course fact.
- This needs a machine with the three indexed courses (whoever ran the 2026-09-23 evaluation).
  This laptop has no `~/.secondmind` index yet.

## 7. Failure analysis (technical analysis, 20%)

Every S3 answer logs:
- the profile block
- the recalled memory ids, with scores and provenance
- the `ops_log` entries for this question's store
- the tool calls

That makes it possible to say **which lifecycle step caused each failure**, not just count
failures. For 30 failed S3 answers (all of them if there are fewer), assign one cause:

| Cause | How to tell |
|---|---|
| Extraction miss | No memory was created from the evidence session |
| Extraction error | A memory was created but it's wrong, or it stores the assistant's words as the student's |
| Consolidation error | Wrong UPDATE, INVALIDATE, or NOOP in `ops_log` |
| Retrieval miss | The right memory existed but wasn't recalled (below the cutoff, or ranked below the top 5) |
| Wrong reasoning | The right memory was recalled; the answer is still wrong (dates, counting, combining facts) |
| Judge error | The human grader disagrees with the judge |

**Edge cases to try on purpose** (student-memory development timelines or one-off scripts):
- A student correcting themselves in the same turn.
- The same entity name in two meanings ("A3" the assignment and "A3" the room).
- "Last Tuesday" said on a Monday.
- A forget request that matches two memories.
- A 30-turn conversation (compression).
- Backend killed mid-job (restart recovery).
- An empty store.
- The grades filter wrongly dropping something (count them).

**The report's "before end-to-end integration" list** comes from this table and the design
spec's §12, not from guesses.

## 8. Cost and latency measurement

- Every LLM call goes through one counting wrapper, which records model, tokens in and out, and
  wall time, per system and per stage (extract, consolidate, answer, judge).
- Dollar figures use the provider's prices on the day of the run, written into the report.
- Answer latency is measured from question to first token and to the last token. S3's background
  write cost is reported separately, because in the product it doesn't delay the answer.

## 9. Budget (rough, worst case with no cache hits)

| Item | Calls | Input tokens |
|---|---|---|
| S3 extraction, 120 questions × ~50 sessions | ~6,000 | ~14M |
| S3 consolidation (estimate: 30% of candidates have neighbors) | ~2,000 | ~2M |
| S1 answering (whole history each time) | 120 | ~14M |
| S0, S2, S3 answering | 360 | < 1M |
| Judge, gpt-4o (4 systems, more with ablations) | 480–840 | < 1M |
| Development runs on the oracle split | — | ~2M |

That's about 30–35M gpt-4o-mini input tokens plus under 1M gpt-4o tokens. At current list prices
that should be well under $20. Check the prices before running. Wall time is a few hours with 8
parallel requests, and the harness can resume from its per-(question, system) cache.

## 10. Harness

```
uv run python3 scripts/memory_eval.py longmemeval --split s --sample ../docs/evaluations/2026-09-28-agent-memory/sample_ids.json \
    --systems S0,S1,S2,S3 [--ablations A1,A2,A3] --out ../docs/evaluations/2026-09-28-agent-memory/
uv run python3 scripts/memory_eval.py longmemeval --split oracle --dev          # tuning only
uv run python3 scripts/memory_eval.py smm --fixtures scripts/memory_eval_fixtures --systems S0,S3
uv run python3 scripts/memory_eval.py judge --in <answers.jsonl>                  # separate step, so it can be rerun
```

- Like `ask_modes_eval.py`, it isn't a pytest test: it makes real, billed calls. The memory
  package's unit tests are offline (design spec §7).
- **Committed:** `sample_ids.json`, LongMemEval answers and judge verdicts (public, synthetic
  data), student-memory grades, and the summary tables.
- **Kept local:** student-memory raw answers, the dataset cache, and the extraction cache.

## 11. Threats to validity

- **Batch size.** Extraction runs per session in the benchmark and per turn in the product. The
  two could differ in quality. The student-memory set runs per turn, which partly covers this.
- **One model.** Only gpt-4o-mini is tested. Results may not carry over to other models.
- **Automated judge.** The judge is an LLM; the 40-answer human check measures how far to trust
  it.
- **Small sample.** 120 questions, 20 per type (§4.6).
- **Who wrote what.** The student-memory set is written by the system's own author. Writing it
  before tuning, and grading blind, limits that bias but doesn't remove it.
- **Different setting.** LongMemEval histories are general chat, not coursework. That's why the
  student-memory set exists.
- **Starting constants.** All the design spec's starting constants are tuned only on the
  development set. The test numbers are the honest ones.

## 12. Demo script (Sprint 5 demonstration)

1. In the app, course 18-654, new chat: "I'm on team 4 with Priya, we're doing the fraud-detection
   project. Please use Java for any examples."
2. Quit and reopen the app. New chat: "What should our project's first milestone cover?" The
   answer uses the project without being told again. `memories_used` shows which memory it used.
3. "Show me how to stub a repository class." The example is in Java.
4. "Actually we switched to the recommender project." Then "What were we doing before?" The answer
   gives both, correctly dated.
5. "Forget that I'm on team 4." `GET /courses/55710/memories` shows the memory is gone. A new
   question about the team gets "I don't know".
6. Show the LongMemEval table (S0/S1/S2/S3 by question type) and the cost-per-answer column.

## 13. Report outline (`report.md`)

1. **What was built** (50%): the lifecycle diagram, what runs in the app, the demo.
2. **Evaluation** (30%):
   - setup and why these baselines
   - the LongMemEval table with intervals, and evidence recall
   - cost and latency
   - the student-memory set
   - regression
3. **Technical analysis** (20%):
   - the failure-cause table (§7)
   - edge cases
   - limitations (§11)
   - calibrated constants vs starting values
   - what must be fixed before Sprint 6 integration
