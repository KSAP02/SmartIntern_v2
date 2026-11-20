import pytest

from backend.services.resume_text import detect_type, extract_text
from backend.tests.conftest import make_docx, make_pdf


def test_detects_and_extracts_docx():
    data = make_docx()
    assert detect_type("cv.docx", data) == "docx"
    text = extract_text(data, "docx")
    assert "Acme Widgets" in text and "FastAPI" in text


def test_detects_and_extracts_pdf():
    data = make_pdf()
    assert detect_type("cv.pdf", data) == "pdf"
    assert "Example Institute of Technology" in extract_text(data, "pdf")


@pytest.mark.parametrize(
    "name,data",
    [
        ("notes.txt", b"hello"),
        ("cv.pdf", b"not really a pdf"),
        ("cv.docx", b"%PDF-1.7 pretending"),
        ("cv.pdf", b"PK\x03\x04 a zip"),
    ],
)
def test_rejects_wrong_or_mismatched_types(name, data):
    assert detect_type(name, data) is None
