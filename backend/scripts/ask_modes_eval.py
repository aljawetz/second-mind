"""Compare three ways of answering chat questions — see
docs/evaluations/2026-09-23-ask-modes/report.md for the write-up.

  A  today's /ask: always search, answer only from what the search returns,
     each question on its own (no chat history).
  B  search as a tool: the model sees the whole chat, decides when and what
     to search, answers only from course material.
  C  same as B, but the model may add its own general knowledge when the
     course doesn't cover something, labeled as such.
  D  C with stricter rules, written after reading the first run's C answers:
     always search, cite a source only for what it actually says, keep all
     general knowledge under the label, copy course numbers exactly.
  E  the shipped /ask code (chat.answer): D plus the report's code fixes,
     at the default 0.5 similarity cutoff.
  F  same as E with a 0.4 cutoff, to choose main.CHAT_SIMILARITY_CUTOFF.

Not a pytest test: makes real, billed OpenAI calls against the real local
index (~/.secondmind/index.lancedb). Run from backend/:

    uv run python3 scripts/ask_modes_eval.py [--set first|heldout] [--only A,B,C,D] [--out PATH]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import openai
from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler
from llama_index.core.query_engine import CitationQueryEngine
from llama_index.llms.openai import OpenAI

import chat
import generation
import indexing
import llm

SM_HOME = Path.home() / ".secondmind"
COURSE_NAMES = {
    55710: "18-654 Software Testing & Operations",
    55016: "18-658 Software Requirements and Interaction Design",
    56350: "Advanced AI for Industry & Society",
}
DEFAULT_COURSE = 55710
MODEL = generation.DEFAULT_MODEL
TEMPERATURE = 0.1  # llama_index's OpenAI default, which mode A already uses
MAX_TOOL_ROUNDS = 4

# Each case is one chat. Single-question cases have one turn.
# kind: course_fact | concept_covered | not_in_course | trap | study_help | follow_up
CASES = [
    # Facts about the course: must come from the materials, never guessed.
    {
        "id": "F1",
        "kind": "course_fact",
        "turns": ["When is the midterm exam?"],
        "gold_source": "syllabus — Grading Algorithm / Tentative Course Calendar (Week 7)",
        "gold_answer": "Oct 7 (Wed of Week 7; Monday 10/05 is the Midterm Review day, not the exam)",
        "gold_confidence": "V",
    },
    {
        "id": "F2",
        "kind": "course_fact",
        "turns": ["How much is the final exam worth?"],
        "gold_source": "syllabus — Grading Algorithm",
        "gold_answer": "20%",
        "gold_confidence": "V",
    },
    {
        "id": "F3",
        "kind": "course_fact",
        "turns": ["What happens if I submit an assignment late?"],
        "gold_source": "syllabus — Late Work Penalty",
        "gold_answer": (
            "10% penalty per day during a 2-4 day grace period (assignment-specific, set in Vocareum); "
            "not accepted once the grace period ends or solutions/grades are published, whichever is first"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "F4",
        "kind": "course_fact",
        "turns": ["When are the TA office hours?"],
        "gold_source": "syllabus — Teaching Assistants",
        "gold_answer": (
            "Chih-Cheng Hsu: Tue 3-5pm in-person (Room 129B); Lan Luo: Thu 3-4pm (Zoom); "
            "Michael Pham: Fri 9-10am (Zoom)"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "F5",
        "kind": "course_fact",
        "turns": ["Can I use ChatGPT for my assignments in this course?"],
        "gold_source": "syllabus — Course-Specific Policy on Using AI and Generative AI Tools",
        "gold_answer": (
            "Permitted with conditions for take-home assignments (must disclose use/extent); not permitted "
            "in graded in-class assignments, quizzes, or exams unless explicitly allowed"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "F6",
        "kind": "course_fact",
        "turns": ["What did the professor say about boundary values in class?"],
        "gold_source": '"08 - BoundaryValues.pdf" (37-slide deck)',
        "gold_answer": (
            "Off-by-one errors framed via a Jeff Atwood quote; boundary value defined as 'a value near the "
            "extreme points of an ordinal input domain, or at/around some special location'; applied to "
            "input-space modeling; four strategies weakest-to-strongest: Normal, Robust, Worst-case, Robust "
            "worst-case; worked example is the NextDate function (month/day/year boundaries, leap years). "
            "No dedicated lecture recording exists for this topic, so verbal-only commentary beyond the "
            "slides can't be confirmed"
        ),
        "gold_confidence": "V",  # slide content only, not a transcript
    },
    {
        "id": "F7",
        "kind": "trap",  # was course_fact — see note below
        "turns": ["How many people can be on a project team?"],
        "gold_source": None,
        "gold_answer": (
            "Not yet available as of this eval's Canvas state (2026-09-28, Week 6 of 14): the 'Course "
            "materials' module stops exactly at Week 6 content, and team formation happens in Week 7 per "
            "the syllabus calendar. Correct behavior says this isn't posted yet, not a guessed number. "
            "Recheck once Week 7+ materials post — the original report's repeat-run noted '5', from an "
            "earlier/different point in the semester or a different source not re-confirmed this session."
        ),
        "gold_confidence": "V",  # the "not yet posted" finding is confirmed; the number itself is not
    },
    # Concepts the course teaches.
    {
        "id": "K1",
        "kind": "concept_covered",
        "turns": ["What is the difference between a stub and a mock?"],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf" (40-slide deck, read in full)',
        "gold_answer": (
            "Taxonomy: Test double -> Stub (aka Dummy), Fake, Spy, Mock, ordered by intrusiveness "
            "Stub < Fake < Spy < Mock. Stub: 'a crude, static stand-in... one-liner methods each returning "
            "a default/prerecorded value.' Mock: 'an object configured at runtime to behave in a certain "
            "way... can verify object interactions, not just results... difficult to implement without a "
            "mocking framework' (EasyMock, JMock, Mockito). Heuristic: 'stub queries, mock actions' (J.B. "
            "Rainsberger) — stub when the test just needs a valid answer, mock when verifying which methods "
            "were called, how many times, how"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "K2",
        "kind": "concept_covered",
        "turns": ["What is a fake object in testing?"],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf", fake-definition slide',
        "gold_answer": (
            "'an optimized, thinned-down version of the real thing that replicates the behavior of the real "
            "thing, but without the persistent or expensive side effects...' A full fake substitutes for "
            "the real object in every context; a restricted/partial fake only in some. Example given: an "
            "in-memory FakeUserRepository standing in for a DB-backed one"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "K3",
        "kind": "concept_covered",
        "turns": ["What is combinatorial testing?"],
        "gold_source": '"08 - CombinatorialTesting.pdf"',
        "gold_answer": (
            "Motivated by defects caused by interactions among blocks/characteristics (cites a stat: 98% of "
            "medical-device defects from pairs of parameters). Three strategies: All-Choice/AC (every "
            "combination — combinatorial explosion), Each-Choice/EC (each block covered at least once — "
            "fewest cases, weakest coverage), All-Pairs aka Pair-Wise/AP (every block paired with every "
            "block of every other characteristic at least once — the practical middle ground)"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "K4",
        "kind": "concept_covered",
        "turns": ["What is test-driven development?"],
        "gold_source": '"L1 - TDD Lab" assignment description + required "TDD Primer.pdf" reading',
        "gold_answer": (
            "'Always lead by tests' — add/modify a test first, then follow compiler errors/IDE suggestions "
            "to add minimal stubbed-out production code, then complete it: 'Test first. Then code. Then "
            "improve, if necessary. Red, Green, Refactor.' Practiced via 'ping-pong' pair programming"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "K5",
        "kind": "concept_covered",
        "turns": ["What is dependency injection and why does it help testing?"],
        "gold_source": '"04 Design For Testability.pdf"',
        "gold_answer": (
            "'Dependency: collaborator that you'd like to replace with a double for testing. Collaborators "
            "should not be instantiated where they are used' — inject via constructor or property/setter "
            "injection so tests can substitute doubles. Supports the course's 'Approximation principle': "
            "doubles approximate collaborators that are unavailable, expensive (slow/resource-intensive), "
            "or non-deterministic"
        ),
        "gold_confidence": "V",
    },
    # Concepts the course materials don't explain (yet).
    {
        "id": "G1",
        "kind": "concept_covered",  # was not_in_course — the course has both a deck and a recording on this
        "turns": ["How does mutation testing work?"],
        "gold_source": '"12 MutationTesting.pdf" + "Mutation testing - lecture recording" page',
        "gold_answer": None,  # module items confirmed to exist; slide content not yet read this session
        "gold_confidence": "U",
    },
    {
        "id": "G2",
        "kind": "not_in_course",
        "turns": ["What is property-based testing?"],
        "gold_source": None,
        "gold_answer": "Not covered by the course materials, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "G3",
        "kind": "not_in_course",
        "turns": ["How does Docker layer caching work?"],
        "gold_source": None,
        "gold_answer": (
            "Docker is covered generally (Weeks 8-9) but layer caching specifically is not, per the "
            "original hand-grading"
        ),
        "gold_confidence": "R",
    },
    {
        "id": "G4",
        "kind": "not_in_course",
        "turns": ["What is the difference between Kubernetes and Docker Swarm?"],
        "gold_source": None,
        "gold_answer": (
            "Course covers Docker Swarm (Week 11) but not Kubernetes, so a K8s-vs-Swarm comparison isn't "
            "in the materials, per the original hand-grading"
        ),
        "gold_confidence": "R",
    },
    # Traps: course facts that are NOT in the materials. The right answer is "I couldn't find that".
    {
        "id": "T1",
        "kind": "trap",
        "turns": ["When is Assignment 5 due?"],
        "gold_source": None,
        "gold_answer": "No such assignment exists — only A0-A4 per the syllabus calendar",
        "gold_confidence": "V",
    },
    {
        "id": "T2",
        "kind": "trap",
        "turns": ["Who is the guest lecturer for the operational excellence class?"],
        "gold_source": None,
        "gold_answer": (
            "Not named in the syllabus calendar; Week 12 just says 'Operational excellence (guest "
            "lecture)' with no name given"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "T3",
        "kind": "trap",
        "turns": ["What grade did I get on A0?"],
        "gold_source": None,
        "gold_answer": "The system has no access to individual grades",
        "gold_confidence": "V",
    },
    # Study help.
    {
        "id": "S1",
        "kind": "study_help",
        "turns": ["Explain test doubles to me like I'm new to programming."],
        "gold_source": None,
        "gold_answer": "Criterion: correct, simplified explanation of test doubles using the course's own terms (see K1), cites a source",
        "gold_confidence": None,
    },
    {
        "id": "S2",
        "kind": "study_help",
        "turns": ["Quiz me with 3 short questions on test doubles."],
        "gold_source": None,
        "gold_answer": "Criterion: 3 questions genuinely testing the test-doubles concept, grounded in course material",
        "gold_confidence": None,
    },
    # Follow-ups: only the later turns are the real test.
    {
        "id": "M1",
        "kind": "follow_up",
        "turns": ["What kinds of test doubles does the course cover?", "Explain the second one."],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf"',
        "gold_answer": (
            "Turn 2 must resolve 'the second one' against whatever list turn 1's own answer gave (course "
            "order: Stub, Fake, Spy, Mock), not re-search cold or pick an unrelated meaning of 'second'"
        ),
        "gold_confidence": "V",  # taxonomy order confirmed; depends on turn 1's actual phrasing
    },
    {
        "id": "M2",
        "kind": "follow_up",
        "turns": ["When is the midterm?", "And the final?"],
        "gold_source": "syllabus — Tentative Course Calendar",
        "gold_answer": "Turn 2: Dec 2 (Wed of Week 14; Monday 11/30 + 2 days)",
        "gold_confidence": "V",
    },
    {
        "id": "M3",
        "kind": "follow_up",
        "turns": [
            "What are boundary values?",
            "Give me a simple example with a function that takes a person's age.",
        ],
        "gold_source": '"08 - BoundaryValues.pdf"',
        "gold_answer": (
            "Turn 2: using the course's own boundary-value definition, a correct age example identifies "
            "min, min+1, max-1, max for the valid range, optionally min-1/max+1 if invoking 'robust' testing"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "M4",
        "kind": "follow_up",
        "turns": [
            "What is the difference between a stub and a mock?",
            "Which one should I use to check that my code sends an email?",
        ],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf"',
        "gold_answer": (
            "Turn 2: a mock — per 'stub queries, mock actions', verifying an email-send call happened is "
            "verifying an action/interaction, which is what mocks (not stubs) are for"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "M5",
        "kind": "follow_up",
        "turns": ["How is the course graded?", "Which part is worth the most?"],
        "gold_source": "syllabus — Grading Algorithm",
        "gold_answer": "Turn 2: Assignments, 30% (the largest single line item)",
        "gold_confidence": "V",
    },
    {
        "id": "M6",
        "kind": "follow_up",
        "turns": ["What is test-driven development?", "Why does that help?", "When is the project due?"],
        "gold_source": "syllabus — Tentative Course Calendar",
        "gold_answer": (
            "Turn 3: the Super-Mutant project has no single due date — it's milestone-based, spread Weeks "
            "9-12 (M1 Wk9 Sun EOD, M2 Wk10 Thu EOD, M3 Wk11 Thu EOD, M4 Wk12 Fri EOD)"
        ),
        "gold_confidence": "V",
    },
]

# Held-out set, written after all four prompts were frozen, to check whether
# the first run's recommendation (D) holds on questions D was never tuned on.
# Two of the three courses here were never used in the first run.
REQ, AI, TST = 55016, 56350, 55710
HELDOUT_CASES = [
    # 18-658 Software Requirements and Interaction Design
    {
        "id": "H1",
        "course": REQ,
        "kind": "course_fact",
        "turns": ["When is the final exam and what format is it?"],
        "gold_source": None,
        "gold_answer": (
            "Not confirmed this session — not stated in the syllabus tab or the assignments list; likely "
            "needs a course-calendar/exam page not yet located (the course's Pages tab has search disabled, "
            "so this means guessing a URL slug, not searching)"
        ),
        "gold_confidence": "U",
    },
    {
        "id": "H2",
        "course": REQ,
        "kind": "course_fact",
        "turns": ["Are the Friday recitations mandatory?"],
        "gold_source": "syllabus — Course Sessions",
        "gold_answer": (
            "The syllabus is self-contradictory: one line says recitations are 'mandatory on 9/25 and "
            "12/4', another says 'mandatory only on December 5' for final presentations. A correct answer "
            "surfaces both dates and the mismatch rather than silently picking one"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "H3",
        "course": REQ,
        "kind": "course_fact",
        "turns": ["What textbook do I need for this class?"],
        "gold_source": "syllabus — Required Textbook",
        "gold_answer": "About Face: The Essentials of Interaction Design, 4th ed. (Cooper, Reimann, Cronin, Noessel; Wiley, 2014)",
        "gold_confidence": "V",
    },
    {
        "id": "H4",
        "course": REQ,
        "kind": "course_fact",
        "turns": ["How long should our field project presentation be?"],
        "gold_source": '"Field Project Objective and Plan of Attack" page',
        "gold_answer": "10-minute presentation",
        "gold_confidence": "V",
    },
    {
        "id": "H5",
        "course": REQ,
        "kind": "concept_covered",
        "turns": ["What makes a good storyboard?"],
        "gold_source": None,
        "gold_answer": "Not confirmed this session — needs a Task 2/3 module page not yet fetched",
        "gold_confidence": "U",
    },
    {
        "id": "H6",
        "course": REQ,
        "kind": "concept_covered",
        "turns": ["How many users do I need for a usability test?"],
        "gold_source": None,
        "gold_answer": (
            "Not confirmed this session — commonly '5 users' (Nielsen), but the course's own number wasn't "
            "located"
        ),
        "gold_confidence": "U",
    },
    {
        "id": "H7",
        "course": REQ,
        "kind": "not_in_course",
        "turns": ["What are Nielsen's 10 usability heuristics? List them."],
        "gold_source": None,
        "gold_answer": "General knowledge only — course doesn't reproduce Nielsen's list verbatim, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "H8",
        "course": REQ,
        "kind": "trap",
        "turns": ["What are Professor Péraire's office hours?"],
        "gold_source": "syllabus — Professor",
        "gold_answer": "The syllabus lists no office hours for Prof. Péraire, only her email — correct answer is 'not listed', not a guess",
        "gold_confidence": "V",
    },
    {
        "id": "H9",
        "course": REQ,
        "kind": "follow_up",
        "turns": [
            "What are the grading weights in this course?",
            "Which single component is worth the most?",
            "And how much is attendance worth?",
        ],
        "gold_source": "syllabus — Grading Rubric",
        "gold_answer": (
            "Turn1 full table: Exam 20%, Jama Lab 5%, Innovation Tasks 1-2 20%, Tasks 3-5 25%, Final "
            "Presentation 5%, Heuristic Eval Lab 5%, Field Project 8%, Class Participation & Attendance "
            "10%, CATME/FCE 2%. Turn2: Innovation Project Tasks 3-5 at 25% is the single largest component. "
            "Turn3: Class Participation and Attendance is 10%"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "H10",
        "course": REQ,
        "kind": "follow_up",
        "turns": ["What are the deliverables for Task 3?", "Which of those involves a video?", "How long can it be?"],
        "gold_source": '"Task 3: Submitting Your Work" page',
        "gold_answer": (
            "Turn1 deliverables: Product Vision, Minimum Valuable Product, Competitive Analysis, Landing "
            "Page w/ Before/After Concept Video & Data Analytics. Turn2: the Landing Page deliverable "
            "involves the video. Turn3: no more than 2 minutes"
        ),
        "gold_confidence": "V",
    },
    # Advanced AI for Industry & Society
    # AI course (id 49797): list_course_files/list_pages/list_assignments all 403'd this session
    # (confirmed real access block, retried with both course ids). H11/H12/H14/H18/H19/H15/H16/H17
    # stay at gold_confidence "R" — the original report's hand-grading, not re-verified — until
    # Canvas access is fixed (per user decision 2026-09-28: fix access, don't block on it).
    {
        "id": "H11",
        "course": AI,
        "kind": "course_fact",
        "turns": ["What are the Big Four AI conferences according to the course?"],
        "gold_source": None,
        "gold_answer": "Not independently confirmed (course 49797 access 403'd); original hand-grading scored all four options Good",
        "gold_confidence": "R",
    },
    {
        "id": "H12",
        "course": AI,
        "kind": "course_fact",
        "turns": ["How many students can be on a project team?"],
        "gold_source": None,
        "gold_answer": "Not independently confirmed (course 49797 access 403'd); original hand-grading scored all four options Good",
        "gold_confidence": "R",
    },
    {
        "id": "H13",
        "course": AI,
        "kind": "course_fact",
        "turns": ["Which citation style should I pick in Zotero?"],
        "gold_source": "Zotero tutorial PDF (used in Sprint 3's own ingestion baseline)",
        "gold_answer": (
            "IEEE — Sprint 3's report found a red box around 'IEEE' marking it as the correct answer on "
            "this exact slide"
        ),
        "gold_confidence": "V",  # via Sprint 3's design doc, not direct Canvas access this session
    },
    {
        "id": "H14",
        "course": AI,
        "kind": "course_fact",
        "turns": ["How recent should the papers in my literature search be?"],
        "gold_source": None,
        "gold_answer": "Not independently confirmed (course 49797 access 403'd)",
        "gold_confidence": "R",
    },
    {
        "id": "H15",
        "course": AI,
        "kind": "trap",
        "turns": ["When is the Sprint 3 deliverable due?"],
        "gold_source": None,
        "gold_answer": "No such Canvas item found, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "H16",
        "course": AI,
        "kind": "trap",
        "turns": ["What percentage of my grade is the LLM certificate?"],
        "gold_source": None,
        "gold_answer": "No LLM-certificate grading component exists, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "H17",
        "course": AI,
        "kind": "not_in_course",
        "turns": ["What is a reranker and why would I use one in a RAG pipeline?"],
        "gold_source": None,
        "gold_answer": "Not covered — general knowledge only, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "H18",
        "course": AI,
        "kind": "follow_up",
        "turns": ["What is the BrainEEG research project about?", "Does their model beat the baseline?"],
        "gold_source": None,
        "gold_answer": "Not independently confirmed (course 49797 access 403'd); original hand-grading scored all four options Good",
        "gold_confidence": "R",
    },
    {
        "id": "H19",
        "course": AI,
        "kind": "follow_up",
        "turns": [
            "What does the Sprint 1 individual assignment ask me to do?",
            "Show me what a filled-in value proposition looks like, using a made-up bike-sharing app.",
        ],
        "gold_source": None,
        "gold_answer": "Not independently confirmed (course 49797 access 403'd)",
        "gold_confidence": "R",
    },
    # 18-654 Software Testing & Operations, topics the first run didn't ask about
    {
        "id": "H20",
        "course": TST,
        "kind": "course_fact",
        "turns": ["Which IDE and build tool does the instructor use for starter code?"],
        "gold_source": None,
        "gold_answer": (
            "Not confirmed this session — needs '01 SVTIntro.pdf' or '01 CourseInfoF26.pdf', not yet read"
        ),
        "gold_confidence": "U",
    },
    {
        "id": "H21",
        "course": TST,
        "kind": "trap",  # was course_fact — see F7's note; same "not yet posted" situation
        "turns": ["How many slip days do I get, and can I use them on the Super-Mutant milestones?"],
        "gold_source": None,
        "gold_answer": (
            "Not yet available as of Week 6 — the Super-Mutant project starts Week 8. The syllabus only "
            "describes a general 2-4 day grace period (10%/day penalty) for labs/assignments, not 'slip "
            "days' specifically. Recheck once project materials post."
        ),
        "gold_confidence": "V",
    },
    {
        "id": "H22",
        "course": TST,
        "kind": "concept_covered",
        "turns": ["What is the hyperassertion problem and how do I fix it?"],
        "gold_source": None,
        "gold_answer": (
            "Not confirmed this session — not located in the decks read so far ('03 Unit Testing "
            "Principles.pdf' doesn't cover it)"
        ),
        "gold_confidence": "U",
    },
    {
        "id": "H23",
        "course": TST,
        "kind": "concept_covered",
        "turns": ["Which kind of test double is the least intrusive?"],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf"',
        "gold_answer": (
            "'(-intrusive) Stub (Dummy) < Fake < Spy < Mock (+intrusive)' — the stub/dummy is the least "
            "intrusive. Guidance given: 'Use weakest double that will do the job'"
        ),
        "gold_confidence": "V",
    },
    {
        "id": "H24",
        "course": TST,
        "kind": "not_in_course",
        "turns": ["How do I set up JaCoCo in a Maven project?"],
        "gold_source": None,
        "gold_answer": "Not covered — course discusses coverage concepts, not JaCoCo/Maven setup specifically, per the original hand-grading",
        "gold_confidence": "R",
    },
    {
        "id": "H25",
        "course": TST,
        "kind": "trap",
        "turns": ["What did the professor cover in Class #2?"],
        "gold_source": None,
        "gold_answer": (
            "Per the original hand-grading, the Class #2 recording is one sentence long — correct behavior "
            "says almost nothing was covered, not an invented agenda"
        ),
        "gold_confidence": "R",
    },
    {
        "id": "H26",
        "course": TST,
        "kind": "follow_up",
        "turns": ["What does 'stub queries, mock actions' mean?", "Show me a short Java example of the second part."],
        "gold_source": '"06 Isolating Components - Test Doubles.pdf", slide "Stub queries, mock actions*" (J.B. Rainsberger)',
        "gold_answer": (
            "Turn1: 'Stub queries' = test needs a valid answer from a collaborator, doesn't care what it "
            "is; 'Mock actions' = test needs to know which methods were called, how many times, how. "
            "Turn2 needs a correct minimal Java/Mockito example of a mocked action (verifying a call "
            "happened)"
        ),
        "gold_confidence": "V",
    },
]

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_course",
        "description": (
            "Search this student's course materials (lecture slides, readings, syllabus, "
            "assignment descriptions, Canvas pages, class recording transcripts). Returns "
            "numbered sources. Use a clear, specific query; you can call it more than once."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to look for."}},
            "required": ["query"],
        },
    },
}

PROMPT_B = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Search the course materials before answering. You can search more than once with different wording.
- Answer only with what the searches return. Cite every factual claim with its source number, like [2].
- If the materials don't cover it, say so plainly. Don't use outside knowledge.
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

PROMPT_C = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Search first whenever the question could be covered by the course: concepts taught, policies, dates, \
assignments, what was said in class. You can search more than once with different wording.
- Facts about this course (dates, grading, policies, deadlines, assignments, staff, what was said in class) \
must come only from search results, with citations like [2]. Never guess them. If the search doesn't find \
them, say you couldn't find it in the course materials.
- When explaining a concept, prefer the course's own material and cite it. If the course doesn't cover it, \
or the student asks for a simpler explanation or an extra example, you may use your general knowledge. Put \
that part after a line that says "General knowledge (not from your course materials):".
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

PROMPT_D = """You are Second Mind, a study assistant for the course {course_name}.
You can search the student's course materials with the search_course tool.

Rules:
- Always search the course materials before answering, including for follow-up questions. You can search \
more than once with different wording. The only exception is when the student only asks you to reformat \
or shorten your previous answer.
- Facts about this course (dates, grading, weights, policies, deadlines, assignments, staff, what was said \
in class) must come only from search results. Copy numbers and dates exactly as the source states them. If \
the source text looks garbled or incomplete, say so instead of guessing. If you can't find it, say you \
couldn't find it in the course materials.
- Only cite a source for a claim that source actually states. Never add a citation to general knowledge.
- Your answer has up to two parts:
  1. What the course materials say, with citations. Leave this part out if they say nothing relevant, and \
say so in one sentence.
  2. Only if it helps (the course doesn't cover it, or the student asked for a simpler explanation or an \
extra example): a part that starts with the line "General knowledge (not from your course materials):". \
Everything you add from your own knowledge goes here, and nothing without a citation goes above it.
- Use the conversation so far to understand follow-up questions.
- Answer first, be concise."""

CITATION_MARK = re.compile(r"\[(\d+)\]")


def source_label(node_with_score) -> str:
    return generation.build_citations([node_with_score])[0]["label"]


# --- mode A: today's pipeline, question only -------------------------------


def run_a(index, question: str, _history: list[dict], _course_name: str) -> dict:
    # Token counts only register through the global callback manager.
    counter = TokenCountingHandler()
    Settings.callback_manager = CallbackManager([counter])
    llm = OpenAI(model=MODEL, api_key=generation._get_llm_key())
    engine = CitationQueryEngine.from_args(
        index,
        llm=llm,
        retriever=generation.HybridRetriever(index),
        citation_qa_template=generation.ANSWER_FIRST_TEMPLATE,
        streaming=False,
    )
    start = time.perf_counter()
    response = engine.query(question)
    elapsed = time.perf_counter() - start
    citations = generation.build_citations(response.source_nodes)
    answer = str(response) if citations else generation.NOT_COVERED_MESSAGE
    return {
        "answer": answer,
        "searches": [question],
        "sources": [c["label"] for c in citations],
        "seconds": round(elapsed, 2),
        "llm_calls": len(counter.llm_token_counts),
        "prompt_tokens": counter.prompt_llm_token_count,
        "completion_tokens": counter.completion_llm_token_count,
    }


# --- modes B and C: tool loop ------------------------------------------------


def run_tool_loop(index, question: str, history: list[dict], system_prompt: str) -> dict:
    client = openai.OpenAI(api_key=generation._get_llm_key())
    retriever = generation.HybridRetriever(index)
    messages = [{"role": "system", "content": system_prompt}]
    for turn in history:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({"role": "user", "content": question})

    searches: list[str] = []
    sources: list[str] = []  # sources[n-1] is source number n
    prompt_tokens = completion_tokens = llm_calls = 0
    start = time.perf_counter()
    for round_num in range(MAX_TOOL_ROUNDS + 1):
        kwargs = {"model": MODEL, "messages": messages, "temperature": TEMPERATURE}
        if round_num < MAX_TOOL_ROUNDS:
            kwargs["tools"] = [SEARCH_TOOL]
        response = client.chat.completions.create(**kwargs)
        llm_calls += 1
        prompt_tokens += response.usage.prompt_tokens
        completion_tokens += response.usage.completion_tokens
        message = response.choices[0].message
        if not message.tool_calls:
            answer = message.content or ""
            break
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            query = json.loads(call.function.arguments).get("query", "")
            searches.append(query)
            nodes = retriever.retrieve(query)
            if not nodes:
                result = "No matching course material found."
            else:
                parts = []
                for n in nodes:
                    sources.append(source_label(n))
                    parts.append(f"[{len(sources)}] {sources[-1]}\n{n.node.get_content()[:1500]}")
                result = "\n\n".join(parts)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    elapsed = time.perf_counter() - start

    cited = sorted({int(m) for m in CITATION_MARK.findall(answer)})
    return {
        "answer": answer,
        "searches": searches,
        "sources": [sources[i - 1] for i in cited if 0 < i <= len(sources)],
        "seconds": round(elapsed, 2),
        "llm_calls": llm_calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }


def run_b(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_B.format(course_name=course_name))


def run_c(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_C.format(course_name=course_name))


def run_d(index, question, history, course_name):
    return run_tool_loop(index, question, history, PROMPT_D.format(course_name=course_name))


def run_shipped(index, question, history, course_name, cutoff):
    searches: list[str] = []
    base_search = chat.make_search(index, cutoff)

    def search(query):
        searches.append(query)
        return base_search(query)

    start = time.perf_counter()
    events = list(chat.answer(question, history, course_name, search, llm.OpenAIProvider(temperature=TEMPERATURE)))
    elapsed = time.perf_counter() - start
    final = next(e for e in events if "citations" in e)
    return {
        "answer": "".join(e.get("delta", "") for e in events),
        "searches": searches,
        "sources": [c["label"] for c in final["citations"]],
        "seconds": round(elapsed, 2),
        "llm_calls": None,  # not exposed by the provider interface
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


def run_e(index, question, history, course_name):
    return run_shipped(index, question, history, course_name, 0.5)


def run_f(index, question, history, course_name):
    return run_shipped(index, question, history, course_name, 0.4)


MODES = {"A": run_a, "B": run_b, "C": run_c, "D": run_d, "E": run_e, "F": run_f}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="A,B,C")
    parser.add_argument("--cases", default="", help="comma-separated case ids; default all")
    parser.add_argument("--set", default="first", choices=["first", "heldout"])
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent.parent.parent / "docs/evaluations/2026-09-23-ask-modes/results.json"),
    )
    args = parser.parse_args()
    modes = args.only.split(",")
    wanted = set(filter(None, args.cases.split(",")))

    cases = HELDOUT_CASES if args.set == "heldout" else CASES
    indexes = {}
    results = []
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        course_id = case.get("course", DEFAULT_COURSE)
        if course_id not in indexes:
            indexes[course_id] = indexing.load_index(SM_HOME / "index.lancedb", f"course_{course_id}")
        index = indexes[course_id]
        for mode in modes:
            history: list[dict] = []
            for turn_num, question in enumerate(case["turns"], start=1):
                out = MODES[mode](index, question, history, COURSE_NAMES[course_id])
                history.append({"question": question, "answer": out["answer"]})
                results.append({"case": case["id"], "course": course_id, "kind": case["kind"], "turn": turn_num, "mode": mode, "question": question, **out})
                print(f"[{case['id']}.{turn_num} {mode}] {out['seconds']}s  searches={out['searches']}", flush=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {len(results)} results to {out_path}")


if __name__ == "__main__":
    main()
