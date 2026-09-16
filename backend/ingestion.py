"""Tiered content extraction — implementation-plan.md Step 5.

plain-text -> density heuristic -> OCR. Tier 4 (vision-model fallback) is
deliberately deferred to Step 8, where the pluggable LLM client actually
gets built — a one-off vision call here would just be redone then.
needs_fallback() marks which pages would need it, so the routing logic is
real even though the call itself isn't yet.
"""

from pathlib import Path

import pdfplumber
import pytesseract
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def needs_fallback(char_count: int, has_image: bool) -> bool:
    """rag-pipeline.md §1's density heuristic, calibrated against 217 real
    pages across 8 files: flag if chars<100, or chars<400 with an image
    present (a page with some text and an image needs a higher bar before
    being trusted as complete, since the image is more likely load-bearing
    when text alone is modest rather than absent)."""
    return char_count < 100 or (char_count < 400 and has_image)


def extract_pdf(path: Path) -> list[dict]:
    """One entry per page: text, char_count, has_image, needs_fallback."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            has_image = len(page.images) > 0
            pages.append(
                {
                    "page": i + 1,
                    "text": text,
                    "char_count": len(text),
                    "has_image": has_image,
                    "needs_fallback": needs_fallback(len(text), has_image),
                }
            )
    return pages


def extract_pptx(path: Path) -> list[dict]:
    """One entry per slide: text, char_count, has_image."""
    slides = []
    prs = Presentation(path)
    for i, slide in enumerate(prs.slides):
        text = "".join(shape.text_frame.text for shape in slide.shapes if shape.has_text_frame)
        has_image = any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in slide.shapes)
        slides.append(
            {
                "slide": i + 1,
                "text": text,
                "char_count": len(text),
                "has_image": has_image,
            }
        )
    return slides


def ocr_pdf_page(path: Path, page_number: int) -> str:
    """Rasterize one PDF page (1-indexed) and run Tesseract on it."""
    with pdfplumber.open(path) as pdf:
        rendered = pdf.pages[page_number - 1].to_image(resolution=200)
        return pytesseract.image_to_string(rendered.original)
