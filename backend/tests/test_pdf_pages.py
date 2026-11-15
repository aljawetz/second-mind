"""ingestion.pdf_page_count and extract_pdf(max_pages=): what the large-file
limit (large_files.py) reads before deciding to index only a preview."""

import ingestion


def _pdf(path, page_texts):
    """A small valid PDF with one line of text per page, offsets computed so
    pdfminer reads it without repairing anything."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in page_texts:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_id = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>"
        )
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


def test_page_count_reads_the_number_of_pages(tmp_path):
    assert ingestion.pdf_page_count(_pdf(tmp_path / "a.pdf", [f"page {i}" for i in range(1, 8)])) == 7


def test_extract_pdf_can_stop_after_the_first_pages(tmp_path):
    path = _pdf(tmp_path / "a.pdf", [f"page {i}" for i in range(1, 8)])
    pages = ingestion.extract_pdf(path, max_pages=3)
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert "page 3" in pages[-1]["text"]
    assert len(ingestion.extract_pdf(path)) == 7
