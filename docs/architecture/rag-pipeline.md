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
   **OCR adds to a page's own text; it never replaces it** (`ingestion.merge_ocr_text`, since
   2026-09-23). It used to replace it, and the flag fires on most slides with a picture on them
   (25 of 43 pages in 18-654's course-info deck). On 9 of those OCR read *less* than the PDF
   already had: the grading slide's "12.5% Project, 17.5% Labs, 30% Assignments…" became just
   "12.5% 17.5%", and "December 2nd" became `December 2"4`. The chat then invented grading weights
   and an exam date from that text. Now only OCR lines made mostly of new words are added, under
   a "[Text read from images on this page]" line, and only when they add at least 5 new words
   in total. That keeps what OCR is actually good for (diagrams, calendars, logos) and drops its
   misreads of text the PDF already had. OCR alone is used only for pages with no text of their
   own.
4. A vision-model pass (the same pluggable LLM client as §3 below) is reserved for pages where OCR
   quality is still poor, or where structural understanding matters (a slide's visual callout, per
   Sprint 3's red-box finding) — opt-in fallback, not a default tier, given its per-page cost.

## 2. Chunking

**Chunks are at most 450 tokens** (`indexing.CHUNK_SIZE`, BGE's own tokenizer), under the
embedding model's 512-token window with room for a heading line. They used to be 700, and the
embedding silently truncates at 512: 23% of real chunks ran past it, and whatever came after
token 512 was invisible to vector search. 18-654's grading table started at token 513 of its
syllabus chunk.

**Canvas HTML (pages, syllabus, assignment descriptions) is split at its own headings**
(`ingestion.extract_html_sections` → `indexing.sections_to_nodes`). A section starts at an
`<h1>`–`<h6>` or at a paragraph that is bold and nothing else, which is how most instructors mark
sections in Canvas's editor ("**Grading Algorithm:**"). Tables stay one row per line with cells
joined by " | " ("12.5% | Project"), list items stay one per line, and every chunk starts with a
path line like `Syllabus › Grading Algorithm`. It used to be flattened into one run of prose, so
the grading table shared a chunk with the staff list and textbooks and never ranked for grading
questions.

A custom `NodeParser` (LlamaIndex's chunking abstraction) that respects the source's natural
structure — a page or a slide is a node, not an arbitrary token window that can split a slide's
content across two chunks. For running prose (pages, the syllabus body, long assignment
descriptions) that exceeds a reasonable node size, LlamaIndex's standard `SentenceSplitter` handles
recursive splitting with overlap (450 tokens, ~15% overlap) so a citation never lands
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
`bge-small-en-v1.5` is converted to ONNX once, on a dev machine, using `optimum[onnx]` — torch
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
[data-model.md](data-model.md) §1).

**Hybrid retrieval is hand-built (`generation.HybridRetriever`), not the integration's own
`query_type="hybrid"` — real finding, this section originally assumed the opposite.** Vector
search alone missed exact name/keyword lookups (a real query about a person named in a class
recording scored only 0.34–0.42 via cosine similarity, well under the grounding cutoff below).
The obvious fix — LlamaIndex's built-in `query_type="hybrid"` — turned out to return a fake score:
`_to_llama_similarities()` falls back to `np.linspace(1, 0, n)` (pure rank position) whenever the
result set lacks a real `score`/`_distance` column, confirmed by testing a deliberately off-topic
control query and finding the top result always scored exactly 1.0 regardless of actual relevance.
That's unusable for a grounding threshold, so `HybridRetriever` keeps two separately-scored
retrieval paths instead of fusing them into one number: real vector search (filtered against
`SIMILARITY_CUTOFF` below) plus LanceDB's raw BM25 full-text search via `table.search(...,
query_type="fts")`. BM25's score magnitude isn't portable across corpora the way cosine similarity
is — confirmed: the same off-topic control query scored ~0 on one real course's corpus and ~4 on a
different one, an order of magnitude apart for the same query, traced to a real, coincidental
keyword match rather than a bug — so the FTS side takes no magnitude threshold at all, only the
single best-ranked match (`FTS_TOP_K = 1`), trusting `CitationQueryEngine`'s own synthesis step as
a verified second line of defense against a weak match slipping through.

**Cited responses come from LlamaIndex's `CitationQueryEngine`**, not a hand-built citation
mechanism — it retrieves (via `HybridRetriever` above), chunks sources at a configurable citation
granularity, and returns a response whose `source_nodes` are the actual chunks the answer was
built from, each carrying the citation-anchor metadata from §2. `generation.build_citations()`
maps `source_nodes` to the citation shape the frontend renders, reading each node's real
`item_type` metadata (`"file"`, `"transcript"`, or `"notes"` — see §6) for `source_type` rather
than assuming every citation is a file.

**Groundedness is enforced inside `HybridRetriever` itself, not via a `node_postprocessor` on the
query engine** — vector nodes are filtered against `SIMILARITY_CUTOFF` (cosine similarity, a real,
portable threshold, calibrated below) before being combined with the FTS nodes, so nothing
downstream re-filters either kind against a scale it was never computed on. If nothing survives,
the pipeline treats that as "nothing relevant is indexed" and returns the not-covered response
(design spec §7) without ever sending an unsupported context to the LLM. **Calibrated against real
retrieval scores** (not guessed): on-topic queries against real indexed content scored
0.6555–0.7524, deliberately off-topic queries scored 0.3077–0.3967 — a clean gap, no overlap.
`SIMILARITY_CUTOFF = 0.5` sits with real margin on both sides, biased slightly toward the
conservative end (reject a borderline match rather than risk an unsupported context reaching the
LLM). 4 on-topic + 3 off-topic queries against one real course — a real data point, not an
exhaustive sweep.

**Tested end-to-end, both retrieval and generation, against real indexed courses** — this section
previously said generation remained untested for lack of an LLM key; that's long since resolved.
`scripts/generation_smoke_test.py` runs real, billed OpenAI calls against a real course's index,
verifying citations and the not-covered case (a deliberately off-topic query returns zero source
nodes, not a hallucinated answer). The real `/ask` endpoint has been exercised
end-to-end through the actual app UI (implementation-plan.md's Q&A frontend wiring and every step
after it), not just via scripts.

## 5. Generation — where LLM provider calls happen

**OpenAI only right now, not the pluggable multi-provider setup this section previously
described.** `generation.py`, `explain.py`, and `sessions.py` each import
`llama_index.llms.openai.OpenAI` directly and hardcode `DEFAULT_MODEL = "gpt-4o-mini"` — there's
no `llama-index-llms-anthropic` dependency, and nothing reads `config.json`'s `llm_provider` back
to select between providers (`OnboardingCourses.tsx` writes it as a static `"openai"` during
onboarding, but no backend code ever reads it). The design intent — LlamaIndex's own multi-
provider LLM abstraction, selected by `llm_provider` with the matching key pulled from Keychain —
is still the plan, just not built; real multi-provider support is future work, not implemented
despite `config.json` already carrying a field that implies it is. The system prompt is what
actually encodes the grounding rules from design spec §7 — answer-first, cite every factual claim,
never blend in open-domain knowledge unless the (separately labeled) web-search path was
explicitly used.

**Course chat is a tool loop, not one retrieve-then-answer pass** (`chat.py`, since 2026-09-23).
The model sees the whole conversation and has one tool, `search_course`, which runs the same
`HybridRetriever` as before and returns numbered results. It can search as many times as it needs
(up to four rounds) before answering. Chosen after comparing four answering styles on 67
questions across three courses (docs/evaluations/2026-09-23-ask-modes/report.md): the old single
pass failed almost every follow-up question ("explain the second one" searched for those exact
words), and a "course only" prompt didn't stop the model from answering from its own knowledge
with unrelated citations. Rules that the prompt alone didn't enforce are in code:
- The student's question is always searched first, word for word, before the model's own
  searches.
- In a follow-up (any history present), the model's first move must be a search in its own
  words (`tool_choice="required"`). Without it, "And the final?" sometimes got "couldn't find it"
  off the word-for-word search, which finds Java's `final` keyword.
- Results are whole chunks. An earlier 1,500-character preview hid answers that sit further down
  a page, and was the real cause of most "not found" misses in the first held-out check.
- Citation numbers are checked and renumbered (`CitationRenumberer`): numbers that match no
  search result are dropped, the rest become 1..k in order of use.
- General knowledge must sit under a fixed label line, which the app shows as its own block.

All model calls for chat go through `llm.py`'s `LLMProvider` interface (OpenAI only today), the
first code on the path to multi-provider support described above. The similarity cutoff for chat
(`main.CHAT_SIMILARITY_CUTOFF`) stays 0.5: 0.4 gave the same number of good answers with one more
made-up fact.

**Fixed: garbled and buried facts.** Chat used to invent 18-654's grading weights in 3 of 3 runs,
because OCR had stripped the grading slide's labels and the syllabus table sat past the embedding
window. After the §1 and §2 fixes and a re-index, it answers with the real weights, citing both the
slide and the syllabus, in 3 of 3 runs. Two weaknesses remain. Relevant chunks often score just
around the 0.5 similarity cutoff (0.49–0.52), so a small change in how a page is chunked can drop
one below it; that needs a better cutoff strategy, not an extraction change. And session
transcripts still have chunks over 512 tokens, because they use their own segment-based chunking.

**Streaming by default** (NFR5, design spec §5) — a Q&A response starts rendering as tokens arrive
rather than waiting for the full completion, which is what makes retrieval-augmented generation
feel conversational instead of like a batch job.

**Cost and latency are real, not abstracted away.** A typical query sends the question plus
several retrieved chunks (roughly a few hundred to low thousands of tokens of context) to the
provider — cheap per-query for text models, but the vision-tier ingestion fallback (§1) is
meaningfully more expensive per page and should stay an opt-in fallback rather than a default,
exactly as Sprint 3 concluded.

## 6. Session capture's nodes

Not in this pipeline's original design — added when session capture (implementation-plan.md Step
12) became the first feature to insert a second, differently-shaped node type into a table a
Canvas sync had already built. `indexing.transcript_to_nodes()` groups consecutive
faster-whisper segments into ~2000-char buffers (split further by the same `SentenceSplitter` as
§2 if a buffer still exceeds the target chunk size), each node's citation anchor a real timestamp
(`"14:22"`) rather than a page/slide number — the same metadata pattern as §2, just a different
anchor kind. `indexing.notes_to_nodes()` indexes the student's own rough in-class notes
separately from the transcript — never fed into the AI note-enhancement step (that reads the
transcript alone, by product decision), but still searchable via Q&A like everything else. Both
carry `item_type` metadata (`"transcript"` / `"notes"`) that §4's citation-building now reads
directly, and both set their `ref_doc_id` to the real `session_id` (`indexing._with_ref_doc()`,
matching data-model.md §4's convention for `canvas_item_id`) — a session/notes citation click can
navigate straight to that session, no lookup needed.

**Real finding: LanceDB infers a table's column schema from whatever the first batch of nodes
happens to contain, and a plain columnar insert can't add a new column later.** A table built from
Canvas pages alone (only ever populating `page`) rejected a later insert of transcript nodes
(populating `timestamp` instead) with `"field 'timestamp' does not exist in table schema"` — the
first time this project ever inserted a second, differently-shaped node type into an existing
table rather than building one fresh in a single batch. Fixed by `indexing._metadata()`: every
node-creation function (`pages_to_nodes`, `slides_to_nodes`, `transcript_to_nodes`,
`notes_to_nodes`) now populates the *same* full metadata key set (`source`, `item_type`, `page`,
`slide`, `timestamp`), leaving whichever keys don't apply to that node kind as `None` rather than
omitted — a schema-compatibility constraint from the storage layer, not a design preference, and
the reason every node in this pipeline carries keys it doesn't use.

**Consistent keys weren't enough: LanceDB also inferred each column's type from the first batch.**
A key that's `None` in every node of a table's first write became type null for good. A course
whose first write was a recorded lecture (`page=None`) then rejected every PDF with "cannot cast
field 'page' from Int64 to Null"; a PDF-first course rejected transcripts and pptx slides. Two of
three real courses had no Canvas files indexed because of it. Fixed by creating each table empty
with an explicit schema (`indexing.TABLE_SCHEMA`) before the first write.

## 7. Study artifacts and the assignment explainer

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
