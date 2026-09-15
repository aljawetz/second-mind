# Sprint 3 — Technical Feasibility and Baseline

**Type:** Team · **Due:** 2026-09-15 · **Points:** 100 · **Status:** Submitted

## Purpose

Test the project's highest-risk assumptions before committing substantial implementation effort.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Technical and Data Feasibility | Identify the most important technical risks; assess required data, APIs, models, infrastructure, tools, hardware, access restrictions, and dependencies | 35% |
| Baseline and Feasibility Prototype | Establish an appropriate baseline and implement a reproducible proof of concept testing at least one critical technical assumption using real or representative data | 45% |
| Findings and Project Decision | Analyze results and limitations; make an evidence-based Proceed, Modify, or Pivot decision with resulting changes to scope or technical direction | 20% |

## Deliverable

3–4 page feasibility report plus working baseline/proof of concept submitted to the project
repository.

---

## 1. Technical and data feasibility

### Highest-risk assumptions

Against the Must Have requirements validated in [Sprint 2](sprint-02.md) (FR1–FR8), the risks that
actually threaten the project — not just anything that could go wrong — are:

1. **Image-heavy PDF and slide ingestion.** Slide decks are the single most valuable content type
   in most courses and the hardest to ingest reliably. This is the risk this sprint's prototype was
   built to test, using real files pulled from a live course.
2. **Canvas ingestion depth (FR2).** Can a student-scoped token actually reach everything a
   student needs indexed — pages, assignments, announcements, modules, files — or does Canvas's
   permission model block parts of it?
3. **Retrieval quality over real course content (FR3, FR4).** Does RAG over real, messy Canvas
   content produce answers a student would actually trust cited? Not tested by this sprint's
   prototype, which validated extraction, not retrieval or generation.
4. **Per-student isolation without a heavy platform (FR6, NFR4).** Can the index be physically
   isolated per student and still run on a student's own machine, without adopting a multi-tenant
   platform built for a shared corpus?
5. **Credential handling across providers (FR1).** Lower technical risk, but a real dependency
   surface: a Canvas token and a pluggable LLM API key, each with its own auth format, stored and
   used locally.
6. **The assignment-explainer's explain-vs-draft boundary (FR8).** Can the model reliably explain
   a prompt and cite material without drifting into drafting an answer? This is a *behavioral*
   risk distinct from retrieval quality — **not tested by this sprint's prototype**. Carried
   forward as an open risk into Sprint 5.

### Data, APIs, models, infrastructure, tools, and access restrictions

| Dependency | Role | Finding |
| --- | --- | --- |
| Canvas REST API | Source of all course content, via the student's own token | `list_course_files` 403s under a student-scoped token even when individual files remain reachable through module items — a real access-pattern quirk to design ingestion around, not just a permission edge case |
| pdfplumber / PyMuPDF | Plain-text extraction and page rasterization for PDFs | Sufficient for text-native PDFs; recovers almost nothing from image-heavy ones — see §2 |
| python-pptx | Native text extraction for PowerPoint files | Strong result on real course material — see §2 |
| Tesseract (local OCR) | Fallback tier for image-heavy pages | Free, fast (4.6s for 11 pages), noisy output — see §2 |
| Vision-capable LLM | Top fallback tier for pages OCR can't resolve | Highest quality, real per-page cost — the same pluggable LLM already in the architecture (§10 of the design spec), not a new dependency |
| Whisper (local transcription) | Planned for lecture capture (FR5) | Not yet built or tested — a Sprint 5/6 dependency, not validated by this sprint |
| Student hardware | Where the whole system must run | OCR ran comfortably on a laptop-class machine in this sprint; the vision-tier's cost/latency at full-course scale is not yet measured |

## 2. Baseline and feasibility prototype

Pulled two real files from a live course (49797, via the same Canvas access this project already
uses) — an 11-page PDF exported from a tutorial-style slide deck, and a 15-slide native PowerPoint
deck — and ran three extraction tiers against each: plain-text extraction (pdfplumber / PyMuPDF for
the PDF, python-pptx for the deck), OCR (Tesseract, on full rasterized pages), and a direct
vision-model read of one representative page.

**The native PPTX extracted well from plain text alone.** 47–664 real text characters per slide
across 15 slides, with only 4 slides containing any embedded picture at all. Native, editable
formats are close to a non-issue for ingestion.

**The PDF was the opposite case.** Plain-text extraction returned 6–300 characters per page (1,614
characters total across 11 pages) — mostly just slide titles. Every page had 1–3 embedded
screenshots, and that's where the actual instructional content lived.

**OCR recovered roughly 3x more text** (4,980 characters total) in 4.6 seconds for all 11 pages —
fast, free, and a real improvement — but the output mixes genuine recovered content ("Choose
IEEE," "Add/edit bibliography") with UI-chrome garbage ("eee Zotero - Document Preferences," "« Z
Zotero|Do xX of <").

**A direct vision-model pass on one representative page produced a clean, structured read**:
correctly identified the dialog, listed all 8 citation style options, and — the one thing neither
other tier caught — recognized that a red box around "IEEE" was a deliberate visual callout
marking it as the correct answer. That's the actual instructional content of the slide, and it's
structurally invisible to both plain-text extraction and OCR.

## 3. Findings and project decision

**Decision: Proceed**, with a specific technical approach for ingestion rather than one strategy
applied uniformly. The core RAG approach and the architecture already laid out in the [design
spec](../specs/2026-09-14-ssb-design.md) §5 both hold — this sprint's finding is about *how* to
ingest PDF and slide content, not whether the overall approach works.

**Extraction should be tiered, not uniform:**

1. Plain-text extraction first — free, instant, and sufficient for native formats and text-heavy
   PDFs, per this sprint's PPTX result.
2. A cheap density heuristic (characters extracted per page, relative to what's expected) flags
   pages likely to be image-heavy — the PDF's 6–300-char pages versus the PPTX's 47–664-char
   slides make the signal obvious.
3. Flagged pages get OCR by default — fast, free, and a real 3x improvement over nothing. A
   vision-model pass is reserved for pages where OCR quality is still poor, or where course
   material is dense enough (annotated screenshots, diagrams with visual emphasis) that structural
   understanding actually matters — accepting the added latency and cost as an opt-in fallback,
   not a default tier.

**Limitations.** This is one 11-page PDF and one 15-slide deck from one course — a real result, not
a comprehensive benchmark. The density heuristic's actual threshold needs tuning against more real
course material before Sprint 5. The vision-tier's per-page cost and latency at full-course scale
(a semester's worth of slide decks) isn't measured yet. Retrieval and generation quality over the
extracted text — as opposed to extraction itself — remain untested, as does the assignment
explainer's explain-vs-draft boundary (FR8); both are open going into Sprint 5.
