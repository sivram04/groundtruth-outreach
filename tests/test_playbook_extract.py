"""Extracting text from an uploaded PDF/DOCX, and the explicit rejection of empty, too-large, unsupported,
malformed, and image-only (no-text) files. Local parsers only; runs in the container that has them."""

from io import BytesIO

import pytest

from outreach import playbook_extract as px


def _docx_bytes(paragraphs):
    import docx
    document = docx.Document()
    for p in paragraphs:
        document.add_paragraph(p)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _blank_pdf_bytes():
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _text_pdf_bytes(text):
    """A minimal, valid single-page PDF with selectable text, built with a correct xref table."""
    def obj(n, inner):
        return f"{n} 0 obj\n{inner}\nendobj\n".encode("latin-1")

    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        obj(1, "<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
               "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        b"4 0 obj\n<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream\nendobj\n",
        obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    body, offsets = b"%PDF-1.4\n", []
    for o in objs:
        offsets.append(len(body))
        body += o
    xref_at = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n" + b"".join(
        f"{off:010d} 00000 n \n".encode("latin-1") for off in offsets)
    return body + xref + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF".encode("latin-1")


def test_a_pdf_with_selectable_text_is_extracted():
    text, kind = px.extract("playbook.pdf", _text_pdf_bytes("Follow up timing playbook"))
    assert kind == "pdf" and "Follow up timing playbook" in text


def test_a_docx_with_text_is_extracted():
    data = _docx_bytes(["## Initial email", "Hi [FIRST_NAME],", "Best,"])
    text, kind = px.extract("playbook.docx", data)
    assert kind == "docx" and "Initial email" in text and "Hi [FIRST_NAME]," in text


def test_an_empty_docx_has_no_text():
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("empty.docx", _docx_bytes([]))
    assert exc.value.reason == "no_text"


def test_an_empty_file_is_rejected():
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("x.pdf", b"")
    assert exc.value.reason == "empty"


def test_an_unsupported_type_is_rejected():
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("notes.txt", b"some text")
    assert exc.value.reason == "unsupported"


def test_an_oversized_file_is_rejected_before_parsing():
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("big.pdf", b"x" * (px.MAX_BYTES + 1))
    assert exc.value.reason == "too_large"


def test_a_malformed_pdf_is_rejected():
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("broken.pdf", b"%PDF-1.4 this is not a real pdf body")
    assert exc.value.reason == "malformed"


def test_an_image_only_pdf_has_no_text():
    # A PDF with pages but no extractable text (a scan) is rejected, not accepted as blank.
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("scan.pdf", _blank_pdf_bytes())
    assert exc.value.reason == "no_text"


def test_a_too_long_playbook_is_rejected():
    data = _docx_bytes(["word " * 20000])  # well over MAX_CHARS once joined
    with pytest.raises(px.PlaybookRejected) as exc:
        px.extract("long.docx", data)
    assert exc.value.reason == "too_long"
