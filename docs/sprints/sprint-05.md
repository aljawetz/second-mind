# Sprint 5 — Core AI/Technology Prototype

**Type:** Team · **Due:** 2026-09-29 · **Points:** 100 · **Status:** Planned

## Purpose

Build the technical capability at the center of the project's value proposition and evaluate
whether it performs meaningfully.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Core Technology Implementation | Implement a functioning version of the project's central AI/software capability (LLMs, RAG, agents, GNNs, foundation models, fine-tuning, traditional ML, cloud systems, etc.) | 50% |
| Evaluation and Baseline Comparison | Evaluate the implementation with appropriate metrics and compare against the Sprint 3 baseline or another appropriate alternative | 30% |
| Technical Analysis | Analyze failures, edge cases, limitations, data/model issues, and the improvements needed before end-to-end integration | 20% |

## Deliverable

Working core prototype, repository update, demonstration, and concise evaluation report.

## Relevant scope

Per [the design spec](../specs/2026-09-14-second-mind-design.md) §4, this is where ingestion, hybrid
retrieval (BM25 + vector, §5.3), and grounded cited Q&A (§7) get built for real, replacing the
[Sprint 3](sprint-03.md) baseline. Retrieval precision@k and citation groundedness (§12) are
the metrics to evaluate against.

## What we did

**Evaluation.** We compared the old chat (the baseline) against three designs where the model
decides when to search, on 67 questions across three real courses, graded blind. The best design
was built into the app (`backend/chat.py`). It gave 28 good answers on the first set (of 34) and
29 on the held-out set (of 33), against 21 and 21 for the old chat, and it answered 13 of 14
follow-ups correctly in every run. An indexing fix later raised the first set to 32 good and 0
bad. We did not yet measure precision@k or a formal citation groundedness score. Concise report:
[docs/evaluations/sprint-5-evaluation-report.md](../evaluations/sprint-5-evaluation-report.md).
Full working report: [docs/evaluations/2026-09-23-ask-modes/report.md](../evaluations/2026-09-23-ask-modes/report.md).

**Earlier pre-validation.** Two pieces got a real pass in Sprint 4 while designing the
architecture, not just planned on paper:

- **Retrieval smoke test.** Indexed real Sprint-3 tiered-extraction content into an actual
  LanceDB table (via LlamaIndex, local `bge-small-en-v1.5` embeddings) and ran four known-answer
  queries — all four retrieved the correct page in the top 3, including one whose answer only
  existed in OCR-recovered text. A 4-query smoke test, not the real precision@k evaluation this
  sprint requires at scale. Full method: [docs/architecture/rag-pipeline.md](../architecture/rag-pipeline.md).
- **Whisper speed test.** `faster-whisper` (base model, CPU) transcribed a 55-second synthetic
  speech sample in 2.5 seconds — a 0.04x real-time factor, confirming local transcription is
  comfortably fast on laptop-class hardware. Accuracy on real classroom audio (background noise,
  accents, room acoustics) is still untested — the synthetic sample was clean, single-voice
  speech, which validates speed, not real-world accuracy.

Generation was untested at that point because no LLM API key was available. The evaluation above
now exercises it with gpt-4o-mini.
