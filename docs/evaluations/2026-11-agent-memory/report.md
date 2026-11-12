# Agent memory evaluation: first results

Second Mind, agent memory and search over past chats. Measured 2026-11-10 with `backend/scripts/memory_eval.py`. Code and commit-by-commit numbers are in PR #56.

The memory layer started out worse than plain search over raw chat turns. After two fixes, a new search over past chats, a higher recall limit and a stronger answering model, it answers 89% of the sample's questions, up from 55%. Everything here is on a development sample of general-chat questions. The full benchmark and anything coursework-specific are still to do (§7).

## 1. What was measured

- **Benchmark:** LongMemEval (`xiaowu0162/longmemeval-cleaned`, MIT). Each question comes with a user's dated past conversations and asks something only those conversations answer.
- **Split:** the oracle split, where a history holds only the sessions that contain the answer (2 to 6 sessions). It tests writing, updating and recalling memories. It does not test finding the answer among 50 unrelated sessions.
- **Samples:** drawn with seed 0.
  - 30 mixed questions, 5 per type (27 answerable, 3 where the right answer is "you never told me").
  - 60 mixed questions, 10 per type (58 answerable).
  - 60 multi-chat questions (54 answerable).
- **Grading:** `gpt-4o` with the benchmark's own judge prompts, one per question type, copied with attribution. An answer is right when the judge says yes.
- **Figures:** answerable questions right, unless stated.

Systems, all answering with the same neutral prompt:

| | System | What it sees |
| --- | --- | --- |
| S0 | Shipped chat window | The last 6 question and answer pairs |
| S1 | Everything in context | Every past session, with dates |
| S2 | Search over raw turns | The 10 turns closest to the question |
| S3 | Memory layer | Sessions replayed through `MemoryService.observe`, then profile, automatic recall, `recall_memory` |
| S4 | Memory layer plus past-chat search | S3, with turns indexed as the app's worker does and `search_past_chats` offered |

## 2. Starting point

30 mixed questions, `gpt-4o-mini` answering:

| System | Right, of 27 | Prompt tokens per answer |
| --- | --- | --- |
| S0 | 16 | 2,054 |
| S1 | 22 | 5,146 |
| S2 | 23 | 4,119 |
| S3 | 14 | 702 |

The memory layer answered with about a sixth of the tokens and got the fewest right. The oracle split flatters S1 and S2: they never have to find the answer among unrelated sessions.

## 3. Why the memory layer missed

Its 13 misses (12 answerable, 1 abstention), read one by one against the stored and recalled memories:

| Cause | Misses |
| --- | --- |
| A fact was not stored, or stored without the detail that decides the answer | 5 |
| By design: the assistant's own words are not stored | 4 |
| Two versions of a fact both kept as current | 1 |
| Recall's top 5 left a needed memory out | 1 |
| Answered where it should have said "not enough information" | 1 |
| Strict judge | 1 |

Recall rarely failed. When the right memory existed it was almost always returned.

## 4. What changed, and what each change did

Single runs on the 60 mixed questions, `gpt-4o-mini` answering. A single run varies by up to four questions (§6), so these show direction, not size.

| Step | Right, of 58 |
| --- | --- |
| Memory layer at the start of the day | 32 |
| Grades filter no longer drops "lost 10 pounds"; extraction prompt asks for dated events and specifics | 35 to 36 |
| Plus `search_past_chats` (S4) | 38 |
| Plus showing the part of a long past answer that matches | 42 to 44 (five runs) |

- **The grades filter** treated "got / lost / received" plus any number as a grade. It now needs a percent, a fraction, points, or "on/in/for" some coursework.
- **Search over past chats** covers what memory deliberately doesn't keep. Questions about what the assistant said went from 0 to 2 of 10 to about 6 of 10. The model called the tool on 8 of 10 of those and on none of the multi-chat questions.
- **The excerpt.** The search returned the right chat 11 times in 12 and the answer was still wrong 5 times, because the detail sat past the first 600 characters of a long answer. Showing the matching stretch fixed 2 of the 4 such cases.

Tried and dropped:

| Idea | Result |
| --- | --- |
| Write memories with `gpt-4o` | 35 of 58 against 36, at 13 times the cost |
| Write memories with `gpt-5.4-mini` | 37 of 58, 8 gained and 7 lost |
| Automatic past-chat search on every question | 18 against 17 of 26 multi-chat questions, at almost twice the prompt tokens |

## 5. Recall limit and answering model

S4, memories written once by `gpt-4o-mini` and reused in every cell, four runs of each. Averages, with the four scores in brackets.

60 mixed questions, of 58:

| Answering model | Recall limit 5 | Recall limit 10 | Median seconds |
| --- | --- | --- | --- |
| `gpt-4o-mini` | 42.8 (42, 44, 42, 43) | 42.0 (43, 42, 42, 41) | 2.7 |
| `gpt-5-mini` | 49.5 (49, 50, 49, 50) | 51.5 (52, 52, 50, 52) | 8.1 |

60 multi-chat questions, of 54:

| Answering model | Recall limit 5 | Recall limit 10 | Median seconds |
| --- | --- | --- | --- |
| `gpt-4o-mini` | 32.5 (32, 34, 30, 34) | 35.2 (36, 35, 36, 34) | 4.6 |
| `gpt-5-mini` | 35.0 (36, 33, 35, 36) | 42.8 (45, 43, 41, 42) | 8.5 |

- **Recall limit 10** helps where a history has many memories (about 20 per multi-chat question) and makes no difference where it has few (about 7). The questions that improved all ask "how many" or "how much in total".
- **`gpt-5-mini`** beat `gpt-4o-mini` in every run of the mixed set. By type, its largest gains are on preferences (9.5 against 6.1 of 10) and on what the assistant said (8.2 against 6.0 of 10).
- **Together** they gain about 10 multi-chat questions, more than the two separately. The stronger model can use the extra memories.
- **`gpt-5-mini` reasons before answering.** About three quarters of its output tokens are hidden reasoning, and an answer takes about three times as long.

Both were adopted: the recall limit is 10 and `gpt-5-mini` is the default OpenAI model.

## 6. How far to trust these numbers

- **Run-to-run variation.** The same setup on the same 60 questions scored between 30 and 34 of 54 across four runs. Single-run differences of two or three questions mean nothing. §5 uses four runs per cell for that reason; §2 and §4 are single runs.
- **No significance tests.** The clearest results are those where every run of one setup beats every run of the other: `gpt-5-mini` against `gpt-4o-mini` on the mixed set, and `gpt-5-mini` at limit 10 on multi-chat questions.
- **The judge is a model.** Its grades were not checked against a person's on this benchmark.
- **The sample was also used for tuning.** The prompt change and the excerpt were designed after reading its misses.

## 7. Not measured yet

- **The full benchmark** (the S split, about 50 sessions per history), where S1 and S2 have to find the answer among unrelated sessions. The comparison in §2 may look different there.
- **Coursework.** LongMemEval is general chat. The student-memory set from the evaluation spec is not built, and the grades filter skipped 52 of 530 turns here, where "due" and "scored" turn up innocently.
- **The rule that a course fact from an old answer is checked with course search** before it is repeated. It is in the prompt and untested with a real model.
- **Whether `gpt-5-mini` improves course chat.** On the `sprint9-chat` set its searches found the same facts (25 of 26) and a turn took 11.7 s at the median against 2.6 s. The judge graded 23 follow-up answers good against 18, but its "bad" grades have been wrong before.
- **A lower reasoning setting for `gpt-5-mini`,** which might buy back speed.
- Evidence recall, ablations and the cost-per-session table from the evaluation spec.

## 8. How to reproduce

From `backend/`, with `.cache/longmemeval/longmemeval_oracle.json` in place:

```
uv run python3 scripts/memory_eval.py --per-type 5 --systems S0,S1,S2,S3 --answer-model gpt-4o-mini --out /tmp/first
uv run python3 scripts/memory_eval.py --per-type 10 --systems S4 --recall-k 10 --out /tmp/mixed
uv run python3 scripts/memory_eval.py --per-type 60 --types multi-session --systems S4 --recall-k 10 --out /tmp/multi
```

These make billed OpenAI calls: about $0.25 the first time a sample's memories are written, about $0.04 to $0.13 a run after that. `--answer-model`, `--recall-k` and `--write-model` set what §4 and §5 vary. The header of `scripts/eval_key.py` says how to store a key for evaluations only.
