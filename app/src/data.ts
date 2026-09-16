import type { AvailableCourse, CourseData } from "./types";

export const DATA: CourseData = {
  "49797": {
    code: "49797 · Advanced AI for Industry and Society",
    sessions: [
      { id: "s1", num: "#6", title: "Grounding and Citation in RAG Systems", date: "Sep 12", duration: "48:12" },
      { id: "s2", num: "#5", title: "Hybrid Retrieval: BM25 + Vector Search", date: "Sep 10", duration: "51:40" },
      { id: "s3", num: "#4", title: "Chunking Strategies for Long Documents", date: "Sep  8", duration: "44:55" },
      { id: "s4", num: "#3", title: "Evaluating LLM Systems in the Wild", date: "Sep  3", duration: "49:20" }
    ],
    qa: {
      q: "What's the difference between retrieval precision@k and answer groundedness?",
      a: [
        "Precision@k measures whether the chunks a retriever returns are relevant to the query — it says nothing about what the model does with them once they're in context.",
        "Groundedness measures the generated answer itself: whether every factual claim in it is actually supported by the retrieved source. A retriever can score well on precision@k and the model can still hallucinate a claim the sources don't back — that's why SSB grades them as two separate metrics rather than assuming one implies the other."
      ],
      sources: ["Lecture 6 · 14:22", "Lecture 5 · 08:05", "Course reader — Ch. 4"]
    },
    session: {
      s1: {
        transcript: [
          ["00:00", "Today we're separating two things people conflate: retrieval quality and answer groundedness."],
          ["02:14", "Precision at k just asks — of the k chunks you retrieved, how many were actually relevant."],
          ["07:41", "Groundedness asks a harder question: does every claim in the generated answer trace back to a chunk."],
          ["14:22", "A system can nail precision@k and still hallucinate at generation time. Those are independent failure modes.", true],
          ["21:03", "This is why SSB grades artifact groundedness separately from answer groundedness — a wrong mock-test question is worse than no mock test."]
        ],
        notes: "- precision@k ≠ groundedness, they fail independently\n- artifact groundedness graded separately (mock test can be \"worse than nothing\")\n- ask: does hybrid BM25+vector change precision@k meaningfully vs. vector-only?"
      }
    },
    mocktest: [
      { q: "Why can a retriever with high precision@k still produce an ungrounded answer?", a: "Precision@k only measures whether retrieved chunks are relevant to the query. Generation is a separate step — the model can still add, misstate, or over-extrapolate beyond what those chunks support. The two failure modes are independent, so both need their own metric.", src: "Lecture 6 · 14:22" },
      { q: "Why does SSB treat artifact groundedness as a separate metric from answer groundedness?", a: "A wrong Q&A answer is visibly wrong and the student can push back immediately. A hallucinated mock-test question isn't caught until the exam — the student studies the wrong thing and finds out too late. That asymmetry is why artifacts get their own bar.", src: "Design spec §8" },
      { q: "What does hybrid BM25 + vector retrieval add over vector-only search?", a: "BM25 catches exact lexical matches — course-specific terms, acronyms, function names — that a dense embedding can blur together. Vector search catches paraphrase and conceptual similarity BM25 misses. Combined, they cover both failure modes of the other.", src: "Lecture 5 · 08:05" }
    ],
    cards: [
      { front: "What does \"grounded\" mean for an SSB answer?", back: "Every factual claim traces to a specific indexed page, file, or transcript segment — if the material doesn't support it, SSB says so instead of guessing." },
      { front: "Answer-first vs. Socratic mode — what's the default?", back: "Answer-first is the default, since that's what students want under time pressure. Socratic mode (guiding questions before the answer) is an opt-in toggle for exam prep." },
      { front: "Why is a shared vector store risky for lecture recordings?", back: "A filter-bug in a shared corpus is a cross-student data leak. Physical per-student isolation turns the same bug into an empty result instead." }
    ],
    slides: [
      { n: "01", title: "RAG Pipeline Overview", bullets: ["Ingest → chunk → embed → index", "Retrieve behind a single interface", "Generate with inline citations"] },
      { n: "02", title: "Chunking Strategies", bullets: ["Fixed-size vs. semantic boundaries", "Image-heavy PDFs need a VLM/OCR pass"] },
      { n: "03", title: "Hybrid Retrieval", bullets: ["BM25 for lexical exact-match", "Vector search for paraphrase", "Merge + re-rank before generation"] },
      { n: "04", title: "Evaluating Groundedness", bullets: ["Citation groundedness rate", "Precision@k vs. answer groundedness", "Graded separately for artifacts"] }
    ],
    mindmap: { center: "RAG System", nodes: ["Ingestion", "Retrieval", "Generation", "Evaluation"] },
    assignments: [
      {
        id: "a1",
        title: "HW3 — RAG Evaluation Report",
        due: "Sep 19",
        weight: "15% of grade",
        status: "Not started",
        prompt: "Build a small evaluation harness for the retrieval pipeline from Lecture 5–6. Given the provided question set and indexed corpus, report retrieval precision@k for k = 3 and k = 5, and separately grade answer groundedness on the same questions using the rubric in the course reader. Submit your harness code, the raw scores, and a one-page write-up comparing what precision@k and groundedness each did — and didn't — catch.",
        explain: {
          breakdown: [
            "Two deliverables, not one: a precision@k measurement on retrieval alone, and a groundedness grade on the generated answers — done separately, not folded into a single score.",
            "The write-up is the actual point of the assignment — it's asking you to find a case where the two metrics disagree, not just report two numbers.",
            "\"Rubric from the course reader\" means you need Ch. 4 open while grading groundedness, not eyeballing it."
          ],
          tips: [
            { text: "Lecture 6 covers exactly why these two metrics can diverge — start there before writing the harness.", src: "Lecture 6 · 14:22" },
            { text: "Lecture 5 walks through the hybrid BM25 + vector setup you'll likely reuse for the retrieval half.", src: "Lecture 5 · 08:05" },
            { text: "The groundedness grading rubric itself lives in the reader, not the lectures.", src: "Course reader — Ch. 4" }
          ]
        }
      }
    ]
  },
  "18654": {
    code: "18654 · Software Testing and Operations",
    sessions: [
      { id: "t1", num: "#4", title: "Flaky Test Detection and Quarantine", date: "Sep 11", duration: "39:18" },
      { id: "t2", num: "#3", title: "Coverage Metrics: What They Don't Tell You", date: "Sep  9", duration: "42:02" },
      { id: "t3", num: "#2", title: "CI Pipeline Design and Fast Feedback", date: "Sep  4", duration: "37:47" }
    ],
    qa: {
      q: "How do you tell a flaky test apart from a real regression?",
      a: [
        "A regression fails deterministically against a specific commit — re-running it against the same code produces the same failure. A flaky test's pass/fail outcome changes across runs with no code change at all, usually from timing, shared state, or ordering dependencies.",
        "The practical test: re-run the failing test in isolation, several times, against an unchanged commit. Consistent failure points to a real regression; inconsistent outcomes point to flakiness — and the fix is different in each case: bisect for a regression, find the race condition for flakiness."
      ],
      sources: ["Lecture 4 · 11:30", "Lecture 2 · 22:10"]
    },
    session: {
      t1: {
        transcript: [
          ["00:00", "Flaky tests erode trust in the suite faster than almost anything else — people stop believing red means broken."],
          ["04:55", "Quarantine isn't the same as ignoring. A quarantined test still runs, it just can't block the pipeline."],
          ["11:30", "The tell: re-run it in isolation against an unchanged commit. If the outcome changes, it's flaky, not a regression.", true],
          ["18:20", "Most flakiness traces to shared state between tests or unmocked wall-clock time — check those two first."]
        ],
        notes: "- quarantine ≠ ignore — still runs, doesn't block\n- re-run in isolation on unchanged commit = the diagnostic\n- check shared state + wall-clock time first"
      }
    },
    mocktest: [
      { q: "What's the operational difference between quarantining a flaky test and deleting it?", a: "A quarantined test keeps running and reporting, it just can't block the pipeline — so you still get signal and a paper trail. Deleting it removes that coverage entirely and the underlying race condition (or real bug) goes unmonitored.", src: "Lecture 4 · 04:55" },
      { q: "Give the standard diagnostic for flaky vs. regression.", a: "Re-run the failing test in isolation, multiple times, against an unchanged commit. A real regression fails consistently; a flaky test's outcome varies with no code change.", src: "Lecture 4 · 11:30" }
    ],
    cards: [
      { front: "Two most common root causes of test flakiness?", back: "Shared state leaking between tests, and unmocked wall-clock/timing dependencies." },
      { front: "What does \"quarantine\" mean for a flaky test in CI?", back: "It keeps running and reporting results, but is excluded from blocking the pipeline until it's fixed." }
    ],
    slides: [
      { n: "01", title: "CI Feedback Loops", bullets: ["Fast path vs. full suite split", "Fail fast on the signal that matters"] },
      { n: "02", title: "Flaky Test Diagnosis", bullets: ["Re-run isolated on unchanged commit", "Shared state + wall-clock are top causes"] },
      { n: "03", title: "Coverage Metrics", bullets: ["Line coverage says nothing about assertion quality", "Mutation testing as a stronger signal"] }
    ],
    mindmap: { center: "Test Suite Health", nodes: ["Flaky Detection", "Coverage", "CI Pipeline", "Postmortems"] },
    assignments: [
      {
        id: "b1",
        title: "Lab 2 — Flaky Test Triage",
        due: "Sep 18",
        weight: "10% of grade",
        status: "Not started",
        prompt: "You're given a repo with a test suite where 4 of 60 tests fail intermittently. Pick 3 of the 4, diagnose the root cause of each — shared state, timing, or ordering — and propose a fix for each (a code diff or a written patch description is fine). Submit a short report: one paragraph per test covering diagnosis, evidence, and fix.",
        explain: {
          breakdown: [
            "Diagnosis before fix, and it wants evidence — a repro or re-run log, not just a guess at the cause.",
            "Three categories to sort into: shared state, timing, ordering. Each of your three picks should land cleanly in one.",
            "The fix can be a written description, not necessarily working code — the prompt explicitly allows \"a diff or a written patch description.\""
          ],
          tips: [
            { text: "This is the exact diagnostic covered here: re-run the failing test in isolation against an unchanged commit.", src: "Lecture 4 · 11:30" },
            { text: "Shared state and unmocked wall-clock timing are named as the two most common root causes — check those first.", src: "Lecture 4 · 18:20" }
          ]
        }
      }
    ]
  }
};

export const WAVE = [8,14,22,16,30,26,12,20,34,28,18,10,24,32,20,14,8,18,26,30,22,12,16,28,34,20,10,24,30,18,14,22,26,16,8,20,32,24,12,18,28,34,20,10,16,24,30,22];

export const AVAILABLE_COURSES: AvailableCourse[] = [
  { code: "49797", name: "Advanced AI for Industry and Society", checked: true },
  { code: "18654", name: "Software Testing and Operations", checked: true },
  { code: "15513", name: "Cost Models for Modern Architectures", checked: false },
  { code: "05899", name: "Special Topics: Behavioral Economics", checked: false },
  { code: "90717", name: "Financial Statement Analysis", checked: false }
];

export const ARTIFACT_TYPES: { key: "mocktest" | "mindmap" | "cards" | "slides"; lbl: string; sub: string }[] = [
  { key: "mocktest", lbl: "Mock Test", sub: "Q&A, cited" },
  { key: "mindmap", lbl: "Mindmap", sub: "Concept graph" },
  { key: "cards", lbl: "Flashcards", sub: "Spaced repeat" },
  { key: "slides", lbl: "Slides", sub: "Condensed deck" }
];
