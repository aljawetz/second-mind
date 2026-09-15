# RAG Pipeline

Ingestion through generation: chunking, embedding, hybrid retrieval, and where LLM provider calls
(OpenAI, Anthropic, etc.) actually happen. See [overview.md](overview.md) for the system shape
this sits inside and [canvas-integration.md](canvas-integration.md) for what feeds into it.

## 1. Ingestion (front door)

Every item that reaches this pipeline has already been fetched by
[canvas-integration.md](canvas-integration.md) or created locally (a session transcript or notes
file). Text-native content (pages, assignments, announcements, notes, transcripts) passes through
as-is. Files go through the tiered extraction validated in Sprint 3:

1. Plain-text extraction (pdfplumber/PyMuPDF for PDFs, `python-pptx` for native slide decks) —
   free, instant, sufficient for text-native formats per Sprint 3's PPTX result.
2. A density heuristic (extracted characters per page) flags pages likely to be image-heavy. **The
   signal is character count, not "does this page contain an image"** — a real 31-page lecture
   deck tested this sprint has images on 25 of 31 pages but still averages ~265 chars/page of real
   bullet-point text, because the images are decorative (icons, small diagrams), not load-bearing.
   That's a different profile from Sprint 3's tutorial-style PDF (6–300 chars/page, where the
   images *were* the content). A starting threshold around 100 chars/page correctly separates the
   two real examples gathered so far — flagging most of the tutorial PDF's pages, leaving the
   lecture deck's pages alone — though it still needs validation at real course scale before
   Sprint 5, not treated as a settled constant.
3. Flagged pages get OCR (Tesseract) by default — free, fast, a real ~3x recovery per Sprint 3.
4. A vision-model pass (the same pluggable LLM client as §3 below) is reserved for pages where OCR
   quality is still poor, or where structural understanding matters (a slide's visual callout, per
   Sprint 3's red-box finding) — opt-in fallback, not a default tier, given its per-page cost.

## 2. Chunking

**Chunk boundaries respect the source's natural structure — a page or a slide is a chunk, not an
arbitrary token window that can split a slide's content across two chunks.** For running prose
(pages, the syllabus body, long assignment descriptions) that exceeds a reasonable chunk size,
fall back to recursive splitting with overlap (target ~500–800 tokens, ~15% overlap) so a citation
never lands mid-sentence. Transcripts chunk along natural speech-segment boundaries (Whisper's own
segment timestamps), which is also what makes a citation like "Lecture 6 · 14:22" possible — the
timestamp is the chunk's own metadata, not something reconstructed after the fact.

Every chunk carries its citation anchor as metadata at creation time: a page number for a file, a
timestamp for a transcript segment, nothing extra for a page/assignment (the item itself is the
citation). This is what lets the answer-generation step (§4) attach a citation without a separate
lookup pass.

## 3. Embedding

**Local, not a hosted API.** Anthropic has no public embeddings endpoint, so "pluggable LLM,
default Claude" (design spec §10) doesn't extend to embeddings regardless of provider choice — an
embedding step is needed either way. Rather than requiring a second provider account just for
embeddings, SSB runs a small open-source embedding model locally (e.g. a BGE-small or comparable
compact sentence-embedding model, small enough to bundle and run on a laptop CPU without a GPU).
This keeps the "self-hosted, your machine" thesis intact for the embedding layer specifically, at
the cost of somewhat lower retrieval quality than the best hosted embedding APIs — a tradeoff
worth revisiting only if retrieval quality turns out to be a real problem in practice, not assumed
upfront.

## 4. Storage and retrieval

**LanceDB**, one database per student, one table per course (design spec §10;
[data-model.md](data-model.md) §1). Each row: `chunk_id, source_item_id, source_type, citation_anchor,
text, vector, full_text` (the last column indexed for BM25-style search). LanceDB's native hybrid
query combines vector similarity and full-text search in one call — no separate BM25 library and
no manual re-ranking step to build and maintain.

**Groundedness is enforced at the retrieval boundary, not left to the LLM's judgment alone.** A
query returns its top-k results with similarity scores; if the top score falls below a set
threshold, the pipeline treats that as "nothing relevant is indexed" and the answer step returns
the not-covered response (design spec §7) without ever sending an unsupported context to the LLM.
The threshold is a tunable constant, not a hard-coded assumption — it needs calibration against
real queries before Sprint 5, the same way Sprint 3 flagged the density heuristic as needing
tuning against more real course material.

## 5. Generation — where LLM provider calls happen

A thin client interface, matching the same "own the interface, not the platform" principle as
`Retriever` (design spec §5.3):

```python
class LLMClient:
    def complete(self, system: str, messages: list[Message], stream: bool = True) -> Completion: ...
```

One implementation per supported provider (OpenAI, Anthropic, etc.), selected by
`config.json`'s `llm_provider` ([data-model.md](data-model.md) §3) with the matching key pulled
from Keychain. The system prompt is what actually encodes the grounding rules from design spec §7
— answer-first by default, Socratic mode as a toggle, cite every factual claim, never blend in
open-domain knowledge unless the (separately labeled) web-search path was explicitly used. The
retrieved chunks from §4 are inserted as context with their citation anchors attached, so the
model's job is to answer *from* them and cite which ones, not to decide on its own what counts as
a source.

**Streaming by default** (NFR5, design spec §5) — a Q&A response starts rendering as tokens arrive
rather than waiting for the full completion, which is what makes retrieval-augmented generation
feel conversational instead of like a batch job.

**Cost and latency are real, not abstracted away.** A typical query sends the question plus
several retrieved chunks (roughly a few hundred to low thousands of tokens of context) to the
provider — cheap per-query for text models, but the vision-tier ingestion fallback (§1) is
meaningfully more expensive per page and should stay an opt-in fallback rather than a default,
exactly as Sprint 3 concluded.

## 6. Study artifacts and the assignment explainer

Both reuse this same retrieval-then-generate shape, not a separate pipeline:

- **Study artifacts** (design spec §8) — retrieve broadly across a module/course rather than
  answering one question, then generate the artifact's structure (mock test questions, mindmap
  nodes, flashcard pairs, slide bullets) with the same per-item citation requirement, graded by the
  same groundedness-threshold logic as §4.
- **Assignment explainer** (design spec §7.1) — retrieves against the assignment's own prompt text
  (reading comprehension of the prompt itself, not course content) plus a course-content retrieval
  pass for the "where to start" pointers. The system prompt here is deliberately narrower: explain
  and cite, never draft — enforced by the interface contract itself having no draft-output field
  ([overview.md](overview.md) §2), not just by prompt instruction.
