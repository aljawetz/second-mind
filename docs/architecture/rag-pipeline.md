# RAG Pipeline

Ingestion through generation: chunking, embedding, hybrid retrieval, and where LLM provider calls
(OpenAI, Anthropic, etc.) actually happen. See [overview.md](overview.md) for the system shape
this sits inside and [canvas-integration.md](canvas-integration.md) for what feeds into it.

**Built on [LlamaIndex](https://developers.llamaindex.ai/), not hand-rolled.** Chunking, embedding
integration, vector storage, hybrid retrieval, and cited response synthesis all have mature,
maintained implementations already — writing our own would mean re-solving problems a
production-grade library has already solved, for no benefit specific to this project. This is a
library used inside our own process, not a platform we deploy: no server, no license gate, no
shared-corpus assumption, unlike Onyx (design spec §10.1). Every LlamaIndex component named below
was checked against its actual current documentation, not assumed from memory.

## 1. Ingestion (front door)

Every item that reaches this pipeline has already been fetched by
[canvas-integration.md](canvas-integration.md) or created locally (a session transcript or notes
file). Text-native content (pages, assignments, announcements, notes, transcripts) passes through
as-is. Files go through the tiered extraction validated in Sprint 3:

1. Plain-text extraction (pdfplumber/PyMuPDF for PDFs, `python-pptx` for native slide decks) —
   free, instant, sufficient for text-native formats per Sprint 3's PPTX result.
2. A density heuristic flags pages likely to be image-heavy, calibrated against 217 real pages
   across 8 files from 2 real courses (lecture decks, a tutorial-style PDF, and academic-paper-style
   PDFs) — not just the original two examples:
   - **A flat character-count cutoff catches the worst cases but misses a real failure mode.**
     15% of all pages tested fall under 100 chars, correctly catching near-empty title/divider
     slides. But a page can clear 100 chars easily on caption text alone while a paired screenshot
     still carries meaningfully more content — found directly on a real page where OCR recovered
     more than double the plain-text character count despite the page already having 301 "real"
     characters. **The actual rule: flag if `chars < 100`, or if `chars < 400` *and* the page
     contains an embedded image** — a page with both some text and an image needs to clear a
     higher bar before being trusted as complete, since the image is more likely to be
     load-bearing when text alone is modest rather than absent.
   - **Content type is a strong, cheap prior.** Every lecture-slide-deck-style PDF tested has a
     real minority of sparse pages (8–29%) needing the OCR/vision fallback. Both academic-paper-
     style PDFs tested (reports, literature reviews) came in at 0–10%. Worth using file/content
     type as a first signal for how aggressively to expect the fallback tiers to matter, not just
     a per-page character count in isolation.
   - Still not a settled constant — 217 pages from 2 courses is a real sample, not a comprehensive
     one, and the exact cutoffs (100, 400) want revisiting once more courses are indexed in
     Sprint 5.
3. Flagged pages get OCR (Tesseract) by default — free, fast, a real ~3x recovery per Sprint 3.
4. A vision-model pass (the same pluggable LLM client as §3 below) is reserved for pages where OCR
   quality is still poor, or where structural understanding matters (a slide's visual callout, per
   Sprint 3's red-box finding) — opt-in fallback, not a default tier, given its per-page cost.

## 2. Chunking

A custom `NodeParser` (LlamaIndex's chunking abstraction) that respects the source's natural
structure — a page or a slide is a node, not an arbitrary token window that can split a slide's
content across two chunks. For running prose (pages, the syllabus body, long assignment
descriptions) that exceeds a reasonable node size, LlamaIndex's standard `SentenceSplitter` handles
recursive splitting with overlap (target ~500–800 tokens, ~15% overlap) so a citation never lands
mid-sentence. Transcripts chunk along natural speech-segment boundaries (Whisper's own segment
timestamps), which is also what makes a citation like "Lecture 6 · 14:22" possible — the timestamp
is the node's own metadata, not something reconstructed after the fact.

Every node carries its citation anchor as LlamaIndex node metadata at creation time: a page number
for a file, a timestamp for a transcript segment, nothing extra for a page/assignment (the item
itself is the citation). Metadata travels with the node through retrieval and into the cited
response automatically — no separate lookup pass needed at answer time.

## 3. Embedding

**Local, not a hosted API.** Anthropic has no public embeddings endpoint, so "pluggable LLM,
default Claude" (design spec §10) doesn't extend to embeddings regardless of provider choice — an
embedding step is needed either way, and a local model avoids requiring a second provider account
just for it.

**How, specifically, matters for packaging — this is the one place the retrieval PoC (§4) used a
path that shouldn't ship.** The PoC used LlamaIndex's `HuggingFaceEmbedding` integration directly
(`BAAI/bge-small-en-v1.5` via `sentence-transformers`), which was the fastest way to validate
retrieval quality. But `sentence-transformers` depends on `torch`, and bundling torch into a
PyInstaller sidecar is a confirmed, well-documented problem — real reports of 3–5GB executables,
worse specifically on macOS due to a shared-library duplication bug in that environment. Measured
directly: a venv with `sentence-transformers` pulls in ~1.8GB including a 583MB torch install; the
same retrieval stack (LlamaIndex core, the LanceDB integration, `faster-whisper`) without it comes
to 874MB with zero torch anywhere.

**What should actually ship: ONNX via `onnxruntime`, not LlamaIndex's `HuggingFaceEmbedding`.**
`bge-small-en-v1.5` is converted to ONNX once, on a dev machine, using `optimum[exporters]` — torch
touches only our own build environment, never a student's machine. The important correction found
by actually checking rather than assuming: LlamaIndex's own ONNX wrapper
(`llama-index-embeddings-huggingface-optimum`) is *not* the clean answer here — it depends on the
`optimum` package, which pulls torch back in as a hard dependency even when only the ONNX/
`onnxruntime` execution path is used. Verified directly by installing it. The actual fix is a small
custom `BaseEmbedding` subclass (a thin wrapper LlamaIndex's interface is designed to support, not
hand-rolling RAG logic) that loads the pre-converted ONNX file via a plain `onnxruntime.InferenceSession`
and tokenizes with the lightweight `tokenizers` library — confirmed torch-free. The converted model
files are small enough to bundle directly in the installer ([overview.md](overview.md) §3),
rather than downloaded from Hugging Face on first run.

This keeps the "self-hosted, your machine" thesis intact for the embedding layer, at the cost of
somewhat lower retrieval quality than the best hosted embedding APIs — a tradeoff worth revisiting
only if retrieval quality turns out to be a real problem in practice, not assumed upfront.

## 4. Storage and retrieval

**LanceDB**, via LlamaIndex's official `LanceDBVectorStore` integration (`llama-index-vector-stores-lancedb`,
actively maintained), one database per student, one table per course (design spec §10;
[data-model.md](data-model.md) §1). LanceDB's native hybrid search (vector + full-text) is exposed
through this integration directly — no separate BM25 library and no manual reranking step to build
and maintain.

**Cited responses come from LlamaIndex's `CitationQueryEngine`**, not a hand-built citation
mechanism — it retrieves, chunks sources at a configurable citation granularity, and returns a
response whose `source_nodes` are the actual chunks the answer was built from, each carrying the
citation-anchor metadata from §2.

**Groundedness is enforced at the retrieval boundary via a `SimilarityPostprocessor`**
(`similarity_cutoff`, a built-in LlamaIndex node postprocessor), not left to the LLM's judgment
alone. Nodes below the cutoff are filtered out before response synthesis ever sees them; if nothing
survives the filter, the pipeline treats that as "nothing relevant is indexed" and returns the
not-covered response (design spec §7) without ever sending an unsupported context to the LLM. The
cutoff value is a tunable constant, not a hard-coded assumption — it needs calibration against real
queries before Sprint 5, the same way Sprint 3 flagged the density heuristic as needing tuning
against more real course material.

**Tested end-to-end (retrieval half) against the real tiered-extraction corpus from Sprint 3.**
Indexed both real files (the Zotero PDF via the full plain-text/OCR pipeline, the lecture deck via
plain text) into an actual `LanceDBVectorStore` with `bge-small-en-v1.5` embeddings, then ran four
known-answer queries through the retriever. All four found the correct page within the top 3
results. The most important result: the query whose answer only exists in OCR-recovered text
("what citation style should I choose") retrieved that page as the **top** result — confirming
that OCR output too noisy to display as a clean citation is still good enough as *embedding input*
for correct retrieval. Those are different bars, and this clears the one retrieval actually needs.
One ranking nuance, not a failure: a query about installation steps ranked an adjacent
install-sequence page above the exact expected one (both topically valid, correct answer still
rank 2 of 3) — worth watching for near-duplicate adjacent content once real courses are indexed at
scale. **This is a 4-query smoke test proving the mechanism works, not a precision@k benchmark** —
that needs many more real queries across more courses at Sprint 5. Generation (the LLM synthesizing
a cited answer from these retrieved nodes) remains untested — no LLM API key was available in this
environment to exercise `CitationQueryEngine`'s synthesis step.

## 5. Generation — where LLM provider calls happen

LlamaIndex's own multi-provider LLM abstraction (`llama-index-llms-openai`,
`llama-index-llms-anthropic`, etc.) wired into the `CitationQueryEngine` from §4, selected by
`config.json`'s `llm_provider` ([data-model.md](data-model.md) §3) with the matching key pulled
from Keychain — not a hand-rolled provider-switch interface. The system prompt is what actually
encodes the grounding rules from design spec §7 — answer-first by default, Socratic mode as a
toggle, cite every factual claim, never blend in open-domain knowledge unless the (separately
labeled) web-search path was explicitly used.

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
  ([overview.md](overview.md) §2), not just by prompt instruction. **Tested against a real coding
  assignment (§7.1): the pointers step needs its own constraint, not just the interface-level one.**
  The prompt must instruct the model to phrase pointers at the topic level ("this lecture covers
  isolating stateful behavior") never at the per-task level ("this task needs a state flag, see
  Lecture 6") — the latter is implementation guidance without being code. Worth a cheap post-hoc
  check (does a pointer's text reference a specific task number or object/method name from the
  prompt?) rather than trusting the system prompt alone, before Sprint 8 treats this as verified.
