# Sprint 7: User, Stakeholder and Impact Validation

Second Mind is an open-source study assistant for Canvas courses. Pilot courses: 49797 (Advanced AI for Industry and Society, primary) and 18654 (Software Testing and Operations).

We asked whether Second Mind solves the problem three students described: course information is scattered and incomplete, and there is no cheap way to check what an AI tells you. Our evidence is three student interviews (two with a live demo) and an automated test of 25 questions on both pilot courses, compared with a plain chatbot. This is a small, early validation. It shows the system answers course questions better than the baseline. It does not show time saved, learning gains or long-term use.

---

## 1. Validation Design and Execution

### 1.1 What we validated

The interviews and the design spec (§1) point to these problems:

1. Course information is hard to find. It sits in modules, files, the syllabus, Drive links and rubrics (Interviewees A and B).
2. Unclear scope and deadlines cost one group about two weeks (Interviewee B).
3. Students check AI answers against their notes or the professor, and they want sources (Interviewees B and C).
4. They already pay for a general chatbot and use it first (Interviewees A, B and C).

We turned these into three hypotheses. We set the thresholds after a first run, so they are descriptive, not pre-registered.


| #   | Hypothesis                                  | "Supported" if                                                                        |
| --- | ------------------------------------------- | ------------------------------------------------------------------------------------- |
| H1  | The assistant finds course facts accurately | Good on at least 80% of course-fact questions, and clearly above the plain chatbot    |
| H2  | Answers can be verified                     | Citation accuracy of at least 80%, and the chat declines instead of inventing         |
| H3  | Cost beats the current setup                | Model cost under $1 per month at 5 questions a day, against a roughly $20 subscription |


### 1.2 Interviews with target users

- **Who.** Three students (Interviewees A, B and C). None came from our pilot courses. Interviewee A is a master's student at a design school. Interviewee C is a recent graduate. The recordings do not say where B studies.
- **How.** 30 to 45 minutes each, with the same eight questions: recent difficulties, where they look beyond Canvas, how they check AI output, and what would convince them a tool improves learning. Interviewees B and C then saw a live demo.

### 1.3 Automated test with a baseline

- **Questions.** 25 in total: 19 on course 18654 and 6 on course 49797. Sixteen are earlier questions with verified answers, 8 are the same facts reworded the way a student would type them, and 1 uses the wrong name for a topic, based on a failed search in an interview.
- **Systems.** The shipped chat (search tool plus cited answers) against a baseline: the same model (gpt-4o-mini) with no search and no course text. The baseline is what a student gets by pasting a question into a general chatbot.
- **Grading.** A stronger model (gpt-4o) rates each answer good, OK or bad against a gold answer. We re-checked the gold answers for the primary course in Canvas on Oct 18. We also hand-graded 10 answers to check the model grader (Section 3.3).
- **Due dates.** A first run showed the chat could not answer "when is X due?", because Canvas keeps due dates outside the assignment text. We added each assignment's due date and points to the indexed text and re-indexed both courses. All results below are from the final run.

---

## 2. Technical and Impact Results

### 2.1 Technical results


| System                   | Good | OK  | Bad | Citation accuracy | Faithful | Recall@5 | Precision@5 | Median time | Cost per answer |
| ------------------------ | ---- | --- | --- | ----------------- | -------- | -------- | ----------- | ----------- | --------------- |
| Shipped chat             | 17   | 6   | 2   | 80%               | 84%      | 73%      | 22%         | 1.8 s       | $0.00035        |
| Plain chatbot (baseline) | 5    | 8   | 12  | n/a               | 76%      | n/a      | n/a         | 1.0 s       | $0.00007        |


The shipped chat was good on 17 of 25 questions (68%). The baseline was good on 5 (20%). The gap comes from course-specific questions:


| Question type                                  | n   | Shipped chat (good / OK / bad) | Plain chatbot |
| ---------------------------------------------- | --- | ------------------------------ | ------------- |
| Course facts (dates, weights, policies)        | 14  | 13 / 1 / 0                     | 0 / 4 / 10    |
| Concepts covered in class                      | 9   | 4 / 4 / 1                      | 4 / 3 / 2     |
| Not stated or personal (Assignment 5, a grade) | 2   | 0 / 1 / 1                      | 1 / 1 / 0     |


- **H1 is supported.** The chat was good on 13 of 14 course-fact questions (93%). The baseline was good on 0 of 14. On general concept questions the two tied, because general software testing is common knowledge.
- **H2 is partly supported.** Citation accuracy is 80%, which meets the threshold, but a model graded it and we did not check citations by hand. On the two questions with no answer in the course, the chat said it could not find the information and invented nothing.
- **Reworded questions** did as well as the originals: 6 good, 2 OK, 0 bad (n=8).
- **Noise.** The baseline's own results changed by about 4 questions between two runs, so small gaps between runs mean little.

### 2.2 Impact results

**Interviews.** All three students go to a general chatbot first and all want a way to verify answers.

- **Interviewee A** loses time finding scattered materials and rubrics, and asks a classmate about details said once in class. 
- **Interviewee B** lost about two weeks to unclear scope and deadlines, and checks AI claims by clicking the cited source. After the demo, B rated the app 8 out of 10. B asked how quiz difficulty is set, worried that graded quizzes could be exposed, and noted there is no logout. B also said the API key is a barrier for non-technical students.
- **Interviewee C** finds AI unreliable on engineering homework and checks with the professor. In the demo, C's search failed when C named a topic differently from the course. C also asked whether formulas in slides are read.

**Cost and ownership (H3 is met).** An answer costs about $0.00035. At 5 questions a day that is about $0.05 per month, against roughly $20 per month for the chatbots the interviewees pay for. Embedding, OCR and storage run on the student's own machine. Only the model call and the Canvas sync leave it.

**Not measured.** Time saved, learning gains, retention and return use during exam weeks.

---

## 3. Findings and Improvement Priorities

### 3.1 What worked

- The chat answers course-specific questions correctly with citations (13 of 14). The plain chatbot cannot.
- When the answer is not in the course, the chat says so.
- Adding due dates to the indexed text fixed the most common student question.
- Model cost is about $0.05 per month.

### 3.2 What did not work

1. **Search fails when the student's wording differs from the course's.** The test question that said "genetic testing" instead of "genetic algorithms" ran five searches, found nothing useful and was graded bad. Interviewee C hit the same failure in the demo.
2. **Search returns many irrelevant passages.** Precision@5 is 22%, even though recall@5 is 73%.
3. **The recorder captures only the microphone**, so Zoom lectures are not covered. We saw this in the demos but did not measure it.
4. **The API key is a barrier** for non-technical students.
5. **Open concerns from the interviews:** graded-quiz exposure, no logout, and quiz difficulty.

### 3.3 Limitations

- Only three interviews, and none from the pilot courses.
- Only 25 test questions, 6 of them on the primary course, so one question is worth 4 points. Most questions come from earlier tests that we used to tune the chat. Only the 8 reworded questions and the 1 wrong-name question are new.
- Recall and precision use a substring match on the source name, so they are only a rough signal.

### 3.4 Priorities for the next iteration


| Rank | Change                                                                              | Why                                                                                              |
| ---- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 1    | Make search work when wording differs: rewrite queries or suggest close topic names | Failed in both the test and a live demo                                                          |
| 2    | Improve retrieval precision                                                         | Precision@5 is only 22%                                                                          |
| 3    | Capture system audio or import lecture recordings                                   | Zoom lectures are not covered                                                                    |
| 4    | Exclude graded quizzes from indexing and add sign-out                               | Raised by Interviewee B; links to Sprint 8 (responsible AI)                                      |
| 5    | Lower the setup barrier (the API key)                                               | Blocks non-technical students                                                                    |
| 6    | Measure time saved and quiz difficulty with students                                | Biggest gap in the evidence; Interviewee B said only test scores without the tool would convince |


---

## Supporting files

In `docs/evaluations/2026-10-sprint7/`: `results.md` (technical detail), `results-after-grades.json` (per-question grades), `judge-check-grades.csv` (our 10 hand grades) and `benchmark-protocol.md` (designed, not run). Interview notes are kept local. Evaluation code: `backend/scripts/ask_modes_eval.py`. The due-date change is `schedule_line` in `backend/course_sync.py`.