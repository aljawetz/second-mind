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

**Local, not a hosted API**, via LlamaIndex's `HuggingFaceEmbedding` integration — confirmed
current documentation supports loading a compact model (e.g. `BAAI/bge-small-en-v1.5`) directly by
name, fully offline once downloaded, no API key or network call at query time. Anthropic has no
public embeddings endpoint, so "pluggable LLM, default Claude" (design spec §10) doesn't extend to
embeddings regardless of provider choice — an embedding step is needed either way, and a local
model avoids requiring a second provider account just for it. This keeps the "self-hosted, your
machine" thesis intact for the embedding layer specifically, at the cost of somewhat lower
retrieval quality than the best hosted embedding APIs — a tradeoff worth revisiting only if
retrieval quality turns out to be a real problem in practice, not assumed upfront.

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
