"""A quiz in the two forms Kahoot imports: Kahoot's spreadsheet template
(render_xlsx, imported as is) and a plain-text PDF for its AI "Extract
questions from the PDF" (render). Kahoot reads the PDF's text, so
the layout is what its extractor and the vendor guides expect: a numbered
question, its options right below it as A) to D), then "Answer: X".

Written by hand (one built-in font, no embedding) so the backend needs no PDF
library: Helvetica with WinAnsiEncoding covers Portuguese and other Latin
text, and anything outside it is spelled out or replaced with "?".
"""

import zlib

# Kahoot's limits for a quiz question and each answer (support article
# "How to make a kahoot"); longer text is cut off or refused on import.
QUESTION_LIMIT = 120
ANSWER_LIMIT = 75

PAGE_W, PAGE_H = 612, 792  # US Letter, in points
MARGIN = 54
# Helvetica advance widths (per 1000 em) for ASCII 32-126, from its AFM.
_WIDTHS = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
# What WinAnsi can't show, spelled out instead of becoming "?".
_SPELLED = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~", "×": "x", "−": "-"}


def _text(s: str) -> str:
    """s in characters Helvetica/WinAnsi can draw."""
    s = " ".join(str(s).split())
    for k, v in _SPELLED.items():
        s = s.replace(k, v)
    return s.encode("cp1252", errors="replace").decode("cp1252")


def _width(s: str, size: float) -> float:
    # Accented letters are as wide as their base letter; 556 covers the rest.
    return sum(_WIDTHS[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in s) * size / 1000


def _wrap(s: str, size: float, width: float) -> list[str]:
    lines, line = [], ""
    for word in s.split(" "):
        candidate = f"{line} {word}" if line else word
        if line and _width(candidate, size) > width:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line]


def _escape(s: str) -> bytes:
    raw = s.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def quiz_lines(title: str, questions: list[dict]) -> list[tuple[str, float, float, str]]:
    """(font, size, indent, text) per line, "" for a gap, before paging."""
    out = [("F2", 16, 0, _text(title)), ("", 0, 0, "")]
    for n, q in enumerate(questions, 1):
        block = [("F2", 11, 0, f"{n}. {_text(q['question'])}")]
        for letter, option in zip("ABCD", q["options"]):
            block.append(("F1", 11, 14, f"{letter}) {_text(option['text'])}"))
        answer = next(letter for letter, o in zip("ABCD", q["options"]) if o["correct"])
        block.append(("F1", 11, 14, f"Answer: {answer}"))
        out += block + [("", 0, 0, "")]
    return out


def render(title: str, questions: list[dict]) -> bytes:
    """The PDF's bytes. A question never splits across pages."""
    usable = PAGE_W - 2 * MARGIN
    pages: list[list[bytes]] = [[]]
    y = PAGE_H - MARGIN

    def lay(items):
        """items' wrapped lines as (font, size, x, text, height)."""
        laid = []
        for font, size, indent, text in items:
            if not font:
                laid.append(("", 0, 0, "", 8))
                continue
            hang = 14 if indent else 0  # an option's later lines line up with its text, not its letter
            for i, part in enumerate(_wrap(text, size, usable - indent - hang)):
                laid.append((font, size, MARGIN + indent + (hang if i else 0), part, size * 1.35))
        return laid

    # Group into blocks (title, then each question with its options) so a
    # block moves to the next page whole.
    lines = quiz_lines(title, questions)
    blocks, current = [], []
    for item in lines:
        current.append(item)
        if not item[0]:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    for block in blocks:
        laid = lay(block)
        height = sum(h for *_, h in laid)
        if y - height < MARGIN and pages[-1]:
            pages.append([])
            y = PAGE_H - MARGIN
        for font, size, x, text, h in laid:
            y -= h
            if font:
                pages[-1].append(b"BT /%s %g Tf %g %g Td (%s) Tj ET" % (font.encode(), size, x, y, _escape(text)))

    # Objects: 1 catalog, 2 page tree, 3-4 fonts, then a page and its content per page.
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, once the pages are known
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for ops in pages:
        stream = zlib.compress(b"\n".join(ops))
        page_no = len(objects) + 1
        kids.append(page_no)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
            % (PAGE_W, PAGE_H, page_no + 1)
        )
        objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def over_limit(questions: list[dict]) -> list[int]:
    """1-based numbers of the questions Kahoot would refuse: a question over 120
    characters or an answer over 75."""
    return [
        n
        for n, q in enumerate(questions, 1)
        if len(q["question"]) > QUESTION_LIMIT or any(len(o["text"]) > ANSWER_LIMIT for o in q["options"])
    ]


# Kahoot's own quiz template (kahoot.com/files/2019/08/Kahoot-Quiz-Spreadsheet-Template.xlsx),
# which its spreadsheet import requires: intro text above, the header on row 8,
# one question per row from row 9 as number, question, answers 1-4, time
# limit and the correct answer's number.
TIME_LIMIT = 30  # seconds; the template allows 5, 10, 20, 30, 60, 90, 120 or 240
_TEMPLATE_INTRO = {
    2: "Quiz template",
    3: "Add questions, at least two answer alternatives, time limit and choose correct answers (at least one). Have fun creating your awesome quiz!",
    4: "Remember: questions have a limit of 120 characters and answers can have 75 characters max. Text will turn red in Excel or Google Docs if you exceed this limit. If several answers are correct, separate them with a comma.",
    5: "See an example question below (don't forget to overwrite this with your first question!)",
    6: "And remember,  if you're not using Excel you need to export to .xlsx format before you upload to Kahoot!",
}
_TEMPLATE_HEADER = [
    "Question - max 120 characters",
    "Answer 1 - max 75 characters",
    "Answer 2 - max 75 characters",
    "Answer 3 - max 75 characters",
    "Answer 4 - max 75 characters",
    "Time limit (sec) – 5, 10, 20, 30, 60, 90, 120, or 240 secs",
    "Correct answer(s) - choose at least one",
]


def render_xlsx(questions: list[dict]) -> bytes:
    """The quiz in Kahoot's spreadsheet template, as .xlsx bytes."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row, text in _TEMPLATE_INTRO.items():
        ws.cell(row, 2, text)
        if row != 5:
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=8)
    for col, text in enumerate(_TEMPLATE_HEADER, 2):
        ws.cell(8, col, text)
    for n, q in enumerate(questions, 1):
        row = 8 + n
        ws.cell(row, 1, n)
        ws.cell(row, 2, " ".join(q["question"].split()))
        for col, option in enumerate(q["options"][:4], 3):
            ws.cell(row, col, " ".join(option["text"].split()))
        ws.cell(row, 7, TIME_LIMIT)
        ws.cell(row, 8, ",".join(str(i) for i, o in enumerate(q["options"][:4], 1) if o["correct"]))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


_FIT_SYSTEM = """You shorten one quiz question so it fits Kahoot's limits: the question at most 110 characters and each answer at most 70, counting spaces and punctuation.
Keep the meaning, the facts and the language. Keep the answers in the same order and still clearly different from each other, and keep the correct one correct and the wrong ones wrong.
Text already short enough stays as it is.
Reply with JSON only: {"question": "...", "answers": ["...", "...", "...", "..."]}"""


def _cut(text: str, limit: int) -> str:
    """text, cut at a word boundary to fit limit with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ,;:-") + "…"


def _rewrite(q: dict, llm) -> dict | None:
    """The LLM's shorter {"question", "answers"} for q, or None."""
    import json

    import json_retry

    asked = {"question": q["question"], "answers": [{"text": o["text"], "correct": bool(o["correct"])} for o in q["options"]]}
    try:
        reply = json_retry.complete_json(
            llm,
            [{"role": "system", "content": _FIT_SYSTEM}, {"role": "user", "content": json.dumps(asked, ensure_ascii=False)}],
            valid=lambda r: isinstance(r, dict)
            and isinstance(r.get("question"), str)
            and r["question"].strip() != ""
            and isinstance(r.get("answers"), list)
            and len(r["answers"]) == len(q["options"])
            and all(isinstance(a, str) and a.strip() for a in r["answers"]),
            label="kahoot.fit",
            temperature=0.2,
        )
    except Exception as e:  # the export must still work if the LLM doesn't
        print(f"[kahoot] shortening failed, cutting instead: {e}", flush=True)
        return None
    return reply if isinstance(reply, dict) else None


def fit(questions: list[dict], llm, only: list[int] | None = None) -> tuple[list[dict], list[int], list[int]]:
    """questions with every one Kahoot would refuse (over_limit), or just
    those numbered in `only`, shortened to fit; the numbers of all the
    questions Kahoot would refuse; and those the LLM didn't manage to rewrite,
    to try again later. One LLM call per question, all at once (a reasoning
    model took minutes over one call for all of them). Whatever the LLM
    leaves too long, or doesn't rewrite, is cut at a word boundary instead,
    so an export always fits."""
    from concurrent.futures import ThreadPoolExecutor

    long = over_limit(questions)
    targets = [n for n in long if only is None or n in only]
    if not targets:
        return questions, long, []
    rewrites: dict[int, dict | None] = {n: None for n in targets}
    if llm is not None:
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            rewrites = dict(zip(targets, pool.map(lambda n: _rewrite(questions[n - 1], llm), targets)))
    fitted = []
    for n, q in enumerate(questions, 1):
        if n not in rewrites:
            fitted.append(q)
            continue
        new = rewrites[n] or {"question": q["question"], "answers": [o["text"] for o in q["options"]]}
        fitted.append(
            {
                **q,
                "question": _cut(new["question"], QUESTION_LIMIT),
                "options": [{**o, "text": _cut(a, ANSWER_LIMIT)} for o, a in zip(q["options"], new["answers"])],
            }
        )
    return fitted, long, [n for n, rewrite in rewrites.items() if rewrite is None]
