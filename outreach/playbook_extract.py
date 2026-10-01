"""Extract the plain text of an uploaded playbook (a PDF or DOCX), locally.

The parsing libraries (`pypdf`, `python-docx`) run in the container and send nothing anywhere - like the
importer's spreadsheet reader. A playbook is only ever read as text to be shown and parsed; its contents
are never treated as instructions to the application and never handed to a model.

Every reason a file is turned away is explicit, so the founder sees what is wrong rather than a blank or a
crash: an empty file, one that is too large, an unsupported type, a malformed/corrupt file, or a file whose
text could not be extracted (an image-only scan).
"""

# Keep the heavy parsers out of import time (as the importer does); a caller that never extracts a file
# needs neither library installed.
MAX_BYTES = 5_000_000          # 5 MB: a cold-outreach playbook is a few pages, never this big
MAX_CHARS = 60_000             # the same ceiling the Drive handbook uses
SUPPORTED = (".pdf", ".docx")


class PlaybookRejected(ValueError):
    """An uploaded playbook could not be used; `reason` is a stable code, `args[0]` the message."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


def _ext(filename):
    name = str(filename or "").strip().lower()
    for ext in SUPPORTED:
        if name.endswith(ext):
            return ext
    return ""


def _pdf_text(data):
    try:
        from pypdf import PdfReader  # local library; imported here so the module loads without it
        from io import BytesIO
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except PlaybookRejected:
        raise
    except Exception as exc:  # a corrupt or encrypted PDF, or a parser error
        raise PlaybookRejected("malformed", f"the PDF could not be read: {exc}") from None


def _docx_text(data):
    try:
        import docx  # python-docx, local
        from io import BytesIO
        document = docx.Document(BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except PlaybookRejected:
        raise
    except Exception as exc:
        raise PlaybookRejected("malformed", f"the DOCX could not be read: {exc}") from None


def extract(filename, data):
    """The playbook's text and its kind ('pdf' or 'docx'). Raises PlaybookRejected with a reason code for
    an empty, too-large, unsupported, malformed, or image-only (no extractable text) file."""
    if not data:
        raise PlaybookRejected("empty", "that file is empty.")
    if len(data) > MAX_BYTES:
        raise PlaybookRejected("too_large",
                               f"that file is {len(data) // 1000} KB; upload a playbook under "
                               f"{MAX_BYTES // 1_000_000} MB.")
    ext = _ext(filename)
    if not ext:
        raise PlaybookRejected("unsupported", "upload a PDF or a DOCX file.")
    text = _pdf_text(data) if ext == ".pdf" else _docx_text(data)
    text = text.replace("\r\n", "\n").replace("﻿", "").strip()
    if not text:
        raise PlaybookRejected("no_text",
                               "no text could be read from that file; a scanned or image-only document "
                               "cannot be used - upload one with selectable text.")
    if len(text) > MAX_CHARS:
        raise PlaybookRejected("too_long",
                               f"that playbook is {len(text)} characters; keep it under {MAX_CHARS}.")
    return text, ext.lstrip(".")
