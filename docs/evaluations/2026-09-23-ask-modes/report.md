# How should Second Mind answer questions? Evaluation report

Date: 2026-09-23
Courses used: 18-654 Software Testing & Operations (first run), plus 18-658 Software Requirements and Interaction Design and Advanced AI for Industry & Society (held-out check)
Model: gpt-4o-mini for every option
Script: `backend/scripts/ask_modes_eval.py` (`--set first` or `--set heldout`)
Grades: `heldout-grades.json`, `shipped-grades.json` (this folder). The raw answers aren't in git: they quote course material, including staff names and emails. Rerun the script to regenerate them (it writes them to this folder, where `.gitignore` keeps them local).

## Final result: the shipped version (read this first)

Option D was built into the app (`backend/chat.py`) with the fixes this report asked for, plus two
more found while testing it. It was then run through both question sets and graded blind again
(two cutoffs shuffled against each other).

| | A. Old chat | D (evaluation) | **Shipped chat** |
|---|---|---|---|
| Good, first set (of 34) | 21 | 30 | **28** |
| Good, held-out set (of 33) | 21 | 24 | **29** |
| Follow-ups right, 3 runs each (of 14) | not run | not run | **13 every run** |

**A correction to the held-out section below.** It said the tool options missed facts because
they search with short keywords. The real cause was a bug in this evaluation: options B, C and D
were only shown the first 1,500 characters of each search result, while the old chat saw whole
chunks. The right page *was* found; the answer sat further down (the final exam date is at
character ~2,470 of its page). The shipped chat sends whole chunks, and those misses went away.

**What the shipped chat adds on top of D:**
- It always searches the student's own words first (fix 1 below).
- In a follow-up, the model *must* search in its own words before answering. Without this, "And
  the final?" sometimes got "couldn't find it", because the word-for-word search finds Java's
  `final` keyword.
- Citation numbers are checked and renumbered in code. No broken citation formats appeared.
- The cutoff stays at 0.5. At 0.4: same number of good answers, one more made-up fact.

**Still wrong:** asked which grading component is worth the most in 18-654, it invented weights
in 3 of 3 runs. The grading slide's text lost its labels ("12.5% 17.5%" only), and the real
breakdown sits deep inside a long syllabus chunk that search never ranks. It also listed made-up
"Class #2 topics" (the Class #2 recording is one sentence). Both need better slide reading and
smaller chunks at indexing time, not a chat change.

Grades: `shipped-grades.json`.

## Update after the held-out check

Option D's rules were written after seeing option C's mistakes on the first question set, so the first result could be biased toward D. To check, we froze all four prompts and wrote 26 new chats (33 questions). Two of the three courses had never been used before. The answers were graded blind: the four answers to each question were shuffled under random letters, and all grades were saved before the letters were matched back to the options.

| | A. Today | B. Tool, course only | C. Tool + own knowledge | D. Stricter C |
|---|---|---|---|---|
| Good, first set (of 34) | 21 | 26 | 28 | 30 |
| **Good, new set (of 33)** | 21 | 22 | 20 | **24** |
| Bad, new set | 6 | 5 | 6 | 6 |
| Follow-ups answered well, new set (of 7) | 2 | **5** | 3 | **5** |
| Confidently wrong course facts, new set | 1 | 2 | 2 | 2 |
| Broken citation format, new set | 0 | 0 | 0 | 7 |

**What changed:**

- **D is still first, but only just.** Its lead went from 9 answers over today's version to 3. On one run of 33 questions, a gap that small could be luck. The first report overstated how much better D is.
- **C fell below today's version.** The bias check mattered: C's loose labeling rules didn't hold up on new courses. D's stricter rules still did better than C (it labeled general knowledge 5 times, C once).
- **Follow-ups still clearly favor the tool options.** B and D answered 5 of 7 follow-ups well. Today's version answered 2. This finding held up.
- **"Better search terms" did not hold up.** On the new courses, the tool options often searched with short keywords ("final exam date") and found nothing, while today's version searched with the student's full sentence and found the answer. All three tool options missed the final exam date and the presentation length that today's version found.
- **The real bottleneck is search, not the chat style.** The 0.5 relevance cutoff was tuned on one course. On the Requirements course, scores bunch up around 0.47 to 0.6, so tiny wording changes decide whether anything is found. "When is the final exam and what format is it?" scores 0.508 (kept). "final exam date" scores 0.49 (thrown away). Some questions failed for every option: all four missed "which single component is worth the most" and "how much is attendance worth", although both are in the syllabus.
- **No option is safer than the others on made-up facts.** On the new set, each tool option confidently stated 2 wrong course facts, and today's version 1. Examples: "individual performance (82%) is the biggest component" (it's a category, not a component), and a list of "Class #2 topics" copied from the course overview slide when the Class #2 recording is one sentence long.

**Updated recommendation:** still build D (tool search, whole chat visible, general knowledge allowed but labeled), because it's the only option that handles follow-ups *and* is honest about what isn't in the course. But fix search first or at the same time, because search misses hurt every option more than the choice of option does:

1. **Always search with the student's own question too,** not only the AI's keywords. Just by doing this, today's version found two answers all three tool options missed, and gave the full grading table where they only gave part of it.
2. **Re-tune the 0.5 cutoff across all courses,** or let the AI see the top results with their scores instead of dropping everything under a fixed line.
3. **Handle citations in code.** D broke the citation format again on new questions (7 of 33).

The original report follows unchanged, apart from this section, the header, and the second appendix.

## Short version (first run only)

- **Today's chat is safe but stuck.** It rarely makes things up, but it fails almost every follow-up question (6 of 7). It also says "not covered" for things a student reasonably wants explained. And it misses some answers that are in the materials, because it searches with the student's exact words.
- **Letting the AI search on its own fixes follow-ups** and finds more answers, because it writes better search terms ("TA office hours" instead of "When are the TA office hours?").
- **Telling the AI "only use the course materials" doesn't work.** When it can't find something, it answers from its own knowledge anyway and attaches citations to slides that don't say that. That's worse than today, because it looks trustworthy.
- **The best option was D:** the AI searches on its own, may use its own knowledge, and must put that under a clear "General knowledge" label. It got the most answers right (30 of 34) and was the most honest about what came from the course.
- **D still needs work before it ships.** Its citation format broke in about half the answers. It misread one garbled date. And it sometimes skipped searching on follow-ups. All three can be fixed in code.
- **Some errors aren't about the chat at all.** They come from how slide PDFs are read (a chart lost its labels, "2nd" became "2"4"). Every option got these wrong.

**Recommendation:** build option D, with the code fixes listed at the end.

## What we compared

| Option | How it works |
|---|---|
| **A. Today** | Every question goes straight to the course search. The AI can only use what comes back. Each question is answered on its own, with no memory of the chat. |
| **B. Search tool, course only** | The AI sees the whole chat and decides when and what to search. It can search more than once. It's told to answer only from the course materials. |
| **C. Search tool + own knowledge** | Same as B, but the AI may use its own knowledge when the course doesn't cover something, under a "General knowledge (not from your course materials)" label. |
| **D. C with stricter rules** | Same as C, but with rules added after reading C's mistakes: always search, only cite a source for what it actually says, keep all general knowledge under the label, copy course numbers exactly. |

## How we tested

We wrote 27 chats (34 questions in total) in six groups:

| Group | Count | Example | What a good answer does |
|---|---|---|---|
| Course facts | 7 | "When is the midterm exam?" | Gives the right fact from the materials, with a source |
| Concepts the course teaches | 5 | "What is the difference between a stub and a mock?" | Explains it the way the course does, with sources |
| Concepts not in the materials | 4 | "How does Docker layer caching work?" | Says the course doesn't cover it, and ideally still helps (clearly labeled) |
| Trick questions | 3 | "When is Assignment 5 due?" (there is no Assignment 5) | Says it couldn't find it. Never makes up an answer. |
| Study help | 2 | "Quiz me with 3 short questions on test doubles." | Does the task using course content |
| Chats with follow-ups | 6 chats, 13 questions | "What kinds of test doubles does the course cover?" then "Explain the second one." | Understands what "the second one" means |

Every question was run once through all four options. The 8 hardest questions were run 2 more times through B, C and D, to check that the results weren't luck.

Each answer was graded by hand against the actual course materials:

- **Good:** correct and useful, sources make sense.
- **OK:** not wrong, but unhelpful or not clearly labeled.
- **Bad:** wrong, made up, or failed to answer something it should have.

## Results

### Overall (first run, 34 questions)

| | A. Today | B. Tool, course only | C. Tool + own knowledge | D. Stricter C |
|---|---|---|---|---|
| Good | 21 | 26 | 28 | **30** |
| OK | 4 | 3 | 4 | 2 |
| Bad | 9 | 5 | 2 | 2 |
| Follow-up questions answered well (of 7) | 1 | **6** | 4 | 4 |
| Answers citing a source that doesn't say that | 0 | 2 | 2 | **0** |
| Made-up course facts | 1 | 2 | 0 | 2 |
| Average time for a full answer | **1.5 s** | 3.3 s | 3.3 s | 3.1 s |
| Cost per question | $0.0003 | $0.0004 | $0.0004 | $0.0004 |

Cost is tiny for every option: about 4 cents per 100 questions.

### By group (number of Good answers)

| Group | A | B | C | D |
|---|---|---|---|---|
| Course facts (7) | 5 | 5 | 7 | 7 |
| Concepts the course teaches (5) | 5 | 5 | 5 | 5 |
| Concepts not in the materials (4) | 0 | 0 | 2 | 4 |
| Trick questions (3) | 3 | 3 | 3 | 3 |
| Study help (2) | 2 | 2 | 2 | 2 |
| Chats with follow-ups (13) | 6 | 11 | 9 | 9 |

### Repeat runs (3 runs each, hardest questions)

| Question | B | C | D |
|---|---|---|---|
| "And the final?" (after asking about the midterm). Right answer: December 2 | Right 3 of 3 | Right 1 of 3 (said Dec 24) | Right 0 of 3 (said Dec 24) |
| "Which part is worth the most?" (after asking about grading) | Made up weights 3 of 3 | Made up weights 2 of 3 (different numbers each time) | Said "not found" 3 of 3 |
| "How does mutation testing work?" (not in the materials) | Wrong citations 3 of 3 | Unclear labels 3 of 3 | Clearly labeled 3 of 3 |
| "Can I use ChatGPT for my assignments?" | Right 1 of 3 | Right 2 of 3 | Right 3 of 3 |

## What we found

### 1. Today's chat can't handle follow-ups

Option A answered 1 of 7 follow-ups well. It doesn't see the chat, so it searches for the follow-up's exact words:

- "Explain the second one." → it explained the second *search result* (something about pair combinations), not fake objects.
- "And the final?" → it explained Java's `final` keyword.
- "Which part is worth the most?" → "The clarity gained by factoring out logical steps ... is worth the most."

Options B, C and D all understood these follow-ups.

### 2. Today's chat misses answers that are in the materials

Searching with the student's exact sentence sometimes misses the right chunk:

- "When are the TA office hours?" → A said they're "TBD". They're listed in the syllabus. B, C and D searched for "TA office hours" and found them.
- "Can I use ChatGPT for my assignments?" → A said there's no information. Slide 38 of the course intro has the AI policy.

### 3. "Only use course materials" is a rule the AI doesn't follow

Option B was told not to use outside knowledge. For "How does mutation testing work?" it still wrote a textbook explanation. Then it cited the syllabus and a slide titled "What is Testing?", neither of which explains mutation testing. This happened in all 3 runs.

The same thing happened with the grading weights: B listed "Midterm 25%, Final Project 25%, Participation 10%, Quizzes 10%". None of that is in the course, and there are no quizzes. (The real weights are Project 12.5%, Labs 17.5%, Assignments 30%, Midterm 20%, Final 20%.)

This is the most important finding. A made-up answer with a real-looking citation is worse than no answer. Today's option A avoids this only because the AI never gets to decide anything.

### 4. Labeling general knowledge works, if the rules are strict

Option C mixed its own knowledge into the course part of the answer, with citations, in several answers. Option D, with stricter wording, kept them apart every time for the "not in the materials" questions:

> The course materials do not provide a specific definition or detailed explanation of how mutation testing works.
>
> General knowledge (not from your course materials): Mutation testing is a technique used to evaluate the quality of software tests. It involves making small changes (mutations) to the program's code ...

It also correctly said "not found" for the grading weights instead of inventing them.

### 5. Option D's own problems

- **Broken citations.** In 15 of 34 answers, D wrote sources as "(source: TDD Primer.pdf, p.1)" or "([source 1](1))" instead of "[1]". Another 3 had no citation markers at all. The app couldn't turn those into clickable sources. The longer prompt seems to have pushed the format around.
- **Skipped searches.** On "Give me a simple example with a function that takes a person's age", D didn't search and didn't label its example as general knowledge. (It's a reasonable example, but the label rule was broken.)
- **Misread date.** See finding 6.

### 6. Some errors come from how PDFs are read, not the chat

These hurt every option:

- The "Grading Rubric" slide is a chart. When the PDF was read, only "12.5%" and "17.5%" survived, without names. A and D both said "deductions account for 12.5% and 17.5%", which is wrong.
- The final exam date on the slide was read as `December 2"4` (it's "2nd" with a small superscript). C and D often turned that into "December 24".
- The syllabus does have the full grading breakdown in plain text, but search never brought that chunk up for grading questions.

Better chat logic can't fix wrong source text.

### 7. Speed

The tool options take about 2 seconds longer for a full answer (3.1 to 3.3 s vs 1.5 s), because the AI first decides what to search. Today's chat also starts showing words sooner because it streams. The tool options can stream their final answer too, but the first words will still come about 1 to 2 seconds later than today.

## Recommendation

Build option D: the AI searches as a tool, sees the whole chat, and may add general knowledge under a clear label. It had the most good answers, the fewest wrong citations, and was the only option that was honest about what it couldn't find.

Don't build option B. It looks safest on paper but made things up the most convincingly.

This also replaces the follow-up questions plan (`docs/superpowers/plans/2026-09-23-follow-up-questions.md`). Follow-ups work with no special code once the AI sees the chat.

### Fixes to make with it

1. **Force a search in code, not only in the prompt.** Require a search on the first step of every answer, so the AI can't skip it. (OpenAI's API has a setting for this. Not tested here yet.)
2. **Handle citations in code.** Tell the AI to use only `[n]`. Remove any number that doesn't match a real search result, and treat answers with no valid citations above the "General knowledge" label as uncited. Don't trust the AI to format sources.
3. **Show the two parts differently in the app.** Course part with clickable sources, general knowledge part visibly marked, so the label doesn't depend only on the AI writing it.
4. **Fix PDF reading for slides.** Charts and superscripts are being garbled ("2nd" → `2"4`). Also check why the syllabus grading chunk doesn't come up in search.
5. **Stream the final answer** so the extra wait is less noticeable.
6. **Update design spec section 7.** It currently says the chat must never use outside knowledge. The new rule would be: course facts only from the materials, with citations; general knowledge allowed, always labeled.
7. **Keep this test as a check.** Rerun `ask_modes_eval.py` after each change, and add questions from the other two courses.

## Limits of this test

- One course, 34 questions. Enough to see clear patterns, not enough for exact percentages.
- The same person (Claude) wrote the questions and graded the answers, so there may be some bias. The raw answers are in this folder if you want to check any grade.
- Option D's rules were written after seeing option C's mistakes on these same questions, so D may look a bit better here than it will on new questions.
- Only gpt-4o-mini was tested. A stronger model might follow the rules better (for example the citation format), at a higher cost.
- Most questions were run once. The 8 hardest were run 3 times.

## Appendix: every grade (first run)

G = Good, O = OK, B = Bad

| Question | A | B | C | D | Notes |
|---|---|---|---|---|---|
| F1 When is the midterm exam? | G | G | G | G | Oct 7 |
| F2 How much is the final exam worth? | G | G | G | G | 20% |
| F3 What happens if I submit late? | G | G | G | G | |
| F4 When are the TA office hours? | B | G | G | G | A said "TBD" |
| F5 Can I use ChatGPT for my assignments? | B | B | G | G | A: "no info". B: only mentioned lab reports |
| F6 What did the professor say about boundary values in class? | G | O | G | G | B used slides, not the class recording |
| F7 How many people on a project team? | G | G | G | G | 5 |
| K1 Stub vs mock | G | G | G | G | |
| K2 What is a fake object? | G | G | G | G | |
| K3 What is combinatorial testing? | G | G | G | G | |
| K4 What is TDD? | G | G | G | G | |
| K5 Dependency injection | G | G | G | G | |
| G1 How does mutation testing work? | O | B | B | G | A: "not covered". B/C: wrong citations |
| G2 What is property-based testing? | O | B | B | G | B cited an unrelated slide. C mixed course and general |
| G3 Docker layer caching | O | O | G | G | A/B: only "not covered" |
| G4 Kubernetes vs Docker Swarm | O | O | G | G | |
| T1 When is Assignment 5 due? | G | G | G | G | All said not found |
| T2 Who is the guest lecturer? | G | G | G | G | All said not found |
| T3 What grade did I get on A0? | G | G | G | G | All said not found |
| S1 Explain test doubles simply | G | G | G | G | |
| S2 Quiz me on test doubles | G | G | G | G | |
| M1 Test double types → "Explain the second one." | G → B | G → G | G → G | G → G | A explained a search result |
| M2 Midterm → "And the final?" | G → B | G → G | G → G | G → B | A: Java `final`. D: Dec 24 |
| M3 Boundary values → "Example with a person's age" | G → B | G → G | G → O | G → O | C/D: example not labeled |
| M4 Stub vs mock → "Which one to check an email is sent?" | G → B | G → G | G → O | G → G | C: no search, no label |
| M5 Grading → "Which part is worth the most?" | B → B | B → B | O → O | B → O | B invented weights. A/D misread the slide |
| M6 TDD → "Why does that help?" → "When is the project due?" | G → B → G | G → G → G | G → G → G | G → G → G | |

## Appendix: held-out grades (graded blind)

G = Good, O = OK, B = Bad. Course: Req = 18-658 Requirements and Interaction Design, AI = Advanced AI for Industry & Society, Testing = 18-654.

| Question | Course | A | B | C | D |
|---|---|---|---|---|---|
| H1.1 When is the final exam and what format is it? | Req | G | B | B | B |
| H2.1 Are the Friday recitations mandatory? | Req | O | O | O | O |
| H3.1 What textbook do I need for this class? | Req | G | G | G | G |
| H4.1 How long should our field project presentation be? | Req | G | B | B | B |
| H5.1 What makes a good storyboard? | Req | G | G | G | G |
| H6.1 How many users do I need for a usability test? | Req | G | G | G | G |
| H7.1 What are Nielsen's 10 usability heuristics? List them. | Req | O | O | O | G |
| H8.1 What are Professor Péraire's office hours? | Req | G | G | G | G |
| H9.1 What are the grading weights in this course? | Req | G | O | O | O |
| H9.2 Which single component is worth the most? | Req | B | B | B | B |
| H9.3 And how much is attendance worth? | Req | B | B | B | B |
| H10.1 What are the deliverables for Task 3? | Req | G | O | O | O |
| H10.2 Which of those involves a video? | Req | O | G | G | G |
| H10.3 How long can it be? | Req | B | G | G | G |
| H11.1 What are the Big Four AI conferences according to the course? | AI | G | G | G | G |
| H12.1 How many students can be on a project team? | AI | G | G | G | G |
| H13.1 Which citation style should I pick in Zotero? | AI | B | G | G | G |
| H14.1 How recent should the papers in my literature search be? | AI | B | G | B | B |
| H15.1 When is the Sprint 3 deliverable due? | AI | G | G | G | G |
| H16.1 What percentage of my grade is the LLM certificate? | AI | G | G | G | G |
| H17.1 What is a reranker and why would I use one in a RAG pipeline? | AI | O | B | O | B |
| H18.1 What is the BrainEEG research project about? | AI | G | G | G | G |
| H18.2 Does their model beat the baseline? | AI | G | G | G | G |
| H19.1 What does the Sprint 1 individual assignment ask me to do? | AI | G | G | G | G |
| H19.2 Show me what a filled-in value proposition looks like, using a made-up bike-sharing app. | AI | G | G | O | G |
| H20.1 Which IDE and build tool does the instructor use for starter code? | Testing | G | G | G | G |
| H21.1 How many slip days do I get, and can I use them on the Super-Mutant milestones? | Testing | G | G | G | G |
| H22.1 What is the hyperassertion problem and how do I fix it? | Testing | O | G | G | G |
| H23.1 Which kind of test double is the least intrusive? | Testing | G | G | G | G |
| H24.1 How do I set up JaCoCo in a Maven project? | Testing | O | O | G | G |
| H25.1 What did the professor cover in Class #2? | Testing | G | O | B | G |
| H26.1 What does 'stub queries, mock actions' mean? | Testing | G | G | G | G |
| H26.2 Show me a short Java example of the second part. | Testing | B | G | O | G |
