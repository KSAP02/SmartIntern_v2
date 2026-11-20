"""Detect resume file type from its bytes and extract plain text (PDF via PyMuPDF, DOCX via python-docx)."""
from __future__ import annotations

import io
import re
import zipfile

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ResumeTextError(ValueError):
    """The file can't be read as a resume. The message is safe to show the user."""


def detect_type(filename: str, data: bytes) -> str | None:
    """Return 'pdf' or 'docx' when BOTH the extension and the content agree, else None."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf" and data.startswith(b"%PDF-"):
        return "pdf"
    if ext == "docx" and data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_text(data: bytes) -> str:
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise ResumeTextError("This PDF could not be opened. It may be damaged or password-protected.") from e
    with doc:
        if doc.needs_pass:
            raise ResumeTextError("This PDF is password-protected. Upload an unprotected copy.")
        return "\n\n".join(page.get_text("text") for page in doc)


def _docx_text(data: bytes) -> str:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        raise ResumeTextError("This DOCX could not be opened. It may be damaged.") from e
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(dict.fromkeys(cells)))
    return "\n".join(parts)


def extract_text(data: bytes, kind: str) -> str:
    if kind == "pdf":
        return _clean(_pdf_text(data))
    if kind == "docx":
        return _clean(_docx_text(data))
    raise ResumeTextError(f"Unsupported file type: {kind}")
