# Sprint 7 technical results: shipped chat vs. plain chatbot

Supporting results for the validation report. Metrics only; raw answers quote course material and stay local (see `.gitignore` in this folder). Per-row grades: [results-after-grades.json](results-after-grades.json).

## What was run

```
cd backend
uv run python3 scripts/ask_modes_eval.py --set sprint7 --only E,G --out ../docs/evaluations/2026-10-sprint7/results-after.json
```

- **E** is the shipped chat (search tool, cited answers, 0.5 similarity cutoff). **G** is the baseline: the same model (gpt-4o-mini) with no search and no course text, which is what a student gets by pasting a question into a general chatbot with nothing attached.
- **Set:** 25 questions, 19 on course 55710 (listed in the spec as 18654, Software Testing and Operations) and 6 on course 56350 (listed in the spec as 49797, Advanced AI). Sixteen are earlier questions with a verified gold answer, 8 are the same facts reworded the way a student would type them (`variant_of`), and 1 is a near-miss question modelled on a failed search seen in an interview (no verified gold, graded on behavior).
- **Due dates:** a first run found the chat could not answer "when is X due?". A fix then added each assignment's due date and points to the text the chat searches (`schedule_line` in `backend/course_sync.py`, with tests) and the two pilot courses' assignments were re-indexed. The results below are from the run after that fix.
- **Grading:** gpt-4o as judge against the gold answer, one call per answer. We hand-graded 10 answers to check it (see Limitations).
- **Metrics:** `correct` (good, ok, bad), `citation_accuracy` (share of citations that support the claim next to them), `faithful` (no course-specific fact without backing), recall@5 and precision@5 (substring match of the expected source in the retrieved labels), latency and cost per answer.

## What changed in the gold answers

Three questions about course 56350 (the Sprint 3 deadline, asked two ways, and the LLM certificate) were treated as "not posted" in earlier runs. Canvas lists both: Sprint 3 is due Tue Sep 15 at 10am, and the LLM certificate is due Tue Nov 10 at 10am, 100 points each (checked in Canvas on Oct 18). Their gold answers were corrected (`SPRINT7_GOLD_FIXES` in the script). The earlier held-out set is untouched.

## Results

| Mode | Good | OK | Bad | Citation accuracy | Faithful | Recall@5 | Precision@5 | p50 s | Avg cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E, shipped chat | 17 | 6 | 2 | 80% | 84% | 73% | 22% | 1.82 | $0.00035 |
| G, plain chatbot | 5 | 8 | 12 | n/a | 76% | n/a | n/a | 1.04 | $0.00007 |

G has nothing to cite, so its citation accuracy (printed as 100% by the script) is left out. G was run twice with the same model and gave 5 good, 12 OK, 8 bad in the first run and 5 good, 8 OK, 12 bad in the second, so differences of a few questions between any two runs are within noise.

By question kind (good / OK / bad):

| Kind | n | E | G |
| --- | --- | --- | --- |
| Course facts (dates, weights, policies) | 14 | 13 / 1 / 0 | 0 / 4 / 10 |
| Concepts covered in class | 9 | 4 / 4 / 1 | 4 / 3 / 2 |
| Not stated or personal (Assignment 5, a grade) | 2 | 0 / 1 / 1 | 1 / 1 / 0 |

By course: 55710 (n=19): E 12 / 6 / 1, G 5 / 8 / 6. 56350 (n=6): E 5 / 0 / 1, G 0 / 0 / 6.

Reworded questions (n=8), E: 6 good, 2 OK, 0 bad. Original wording (n=16, without the near-miss case): 11 good, 4 OK, 1 bad.

## Reading the results

1. **Course-specific facts are where the system adds value.** The shipped chat was good on 13 of 14 questions about dates, weights and policies and never bad. The plain chatbot was good on 0 of 14 and bad on 10 (it guessed or could not know). This matches the pain interviewees described.
2. **Due dates work after the fix.** A first run could not answer "When is the Sprint 3 deliverable due?" and "when do we hand in the third sprint deliverable" and got "I couldn't find it in the course materials". The indexed text of those assignments held no due date (Canvas keeps it on the assignment record, not in the description). After adding "Due Tue, Sep 15, 2026 at 10:00 AM PDT. Worth 100 points." to each assignment's indexed text, both questions were answered correctly with a citation, and the LLM-certificate question now gets its due date and points.
3. **Side effect: retrieval may be a little noisier.** Every assignment now has an extra short chunk that can compete for queries that mention "sprint" or "deliverable". We did not measure this against a run without the due-date chunks, so it should be watched.
4. **Rewording did not hurt, with one exception.** The reworded questions did at least as well as the originals. The exception is the near-miss question where the student used the wrong name for a topic ("genetic testing" for "genetic algorithms"). The shipped chat ran five searches, found nothing usable and was graded bad both times, the same failure Interviewee C hit in the demo. The plain chatbot also failed.
5. **On questions with no answer in the materials, the shipped chat declined every time by hand reading.** For the two such questions (a nonexistent Assignment 5 and a personal grade) it said it could not find the information and invented nothing. The judge's "correct abstention" rate disagrees with that reading and should not be quoted; the judge also graded the plain chatbot's equivalent refusals inconsistently.
6. **Retrieval is imprecise.** Recall@5 was 73% but precision@5 only 22%: the expected source is usually in the top results, but most returned passages are not from it. Cited answers still reached 80% citation accuracy, so the model mostly cites the right passage out of a noisy set.
7. **Cost and speed.** Median 1.8 s and about $0.00035 per answer for the shipped chat, about 5 times the plain chatbot's cost. At an assumed 5 questions per day that is roughly $0.05 per month in model cost, before embedding, which runs locally.

## Limitations

- Small set (25 questions, 6 on the primary course). A difference of one question is 4 points, and the plain chatbot's own run-to-run variation was about that large.
- Most questions come from earlier evaluation sets, so the shipped chat's prompt was tuned on some of the same course material. The 8 reworded and 1 near-miss questions are the only new ones.
- LLM judge. We hand-graded 10 shipped-chat answers and rated all 10 good; the judge rated 4 good, 4 OK and 2 bad, so we agreed on 4 of 10. The judge was stricter on incomplete answers and refusals. One grader who knew the course did the check, and citation ratings were not checked. Read judge-based good counts as conservative. Its abstention check disagrees with a hand reading and is not quoted.
- Recall and precision use a substring match on the source name; use as a signal, not an exact number.
- The baseline is the same small model without tools. A larger chatbot given the course PDFs would do better than G; that comparison was not run.
- Due times print in the student's computer timezone (Pacific here), which matches what Canvas shows this student.
