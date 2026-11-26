"""
parser.py
---------
Extracts raw text from uploaded resume files (PDF, DOCX, TXT) and does
light cleanup/normalisation so downstream scoring gets consistent input.

Design notes:
- Each file type has its own extractor function so it's easy to add a
  new format (e.g. .rtf, .html) later without touching calling code.
- extract_text() is the single public entry point; it dispatches on
  file extension and raises a ParsingError with a clear message on
  failure instead of letting a raw exception bubble up to the API layer.
"""

import io
import os
import re

import pdfplumber
import docx  # python-docx


class ParsingError(Exception):
    """Raised when a resume/JD file cannot be parsed."""


def _extract_pdf(file_stream: io.BytesIO) -> str:
    text_chunks = []
    try:
        with pdfplumber.open(file_stream) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_chunks.append(page_text)
    except Exception as exc:  # noqa: BLE001 - convert to domain error
        raise ParsingError(f"Could not read PDF file: {exc}") from exc
    return "\n".join(text_chunks)


def _extract_docx(file_stream: io.BytesIO) -> str:
    try:
        document = docx.Document(file_stream)
    except Exception as exc:  # noqa: BLE001
        raise ParsingError(f"Could not read DOCX file: {exc}") from exc
    paragraphs = [p.text for p in document.paragraphs]
    # Also pull text out of any tables (skills tables, etc.)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.append(cell.text)
    return "\n".join(paragraphs)


def _extract_txt(file_stream: io.BytesIO) -> str:
    try:
        raw = file_stream.read()
        return raw.decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        raise ParsingError(f"Could not read TXT file: {exc}") from exc


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".txt": _extract_txt,
}

SUPPORTED_EXTENSIONS = tuple(_EXTRACTORS.keys())


def normalise_text(text: str) -> str:
    """Collapse whitespace and lowercase for consistent downstream matching."""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(filename: str, file_bytes: bytes) -> str:
    """
    Extract text from a resume/JD file.

    Args:
        filename: original filename (used to determine extension)
        file_bytes: raw file content

    Returns:
        Normalised plain text.

    Raises:
        ParsingError: on unsupported extension or extraction failure.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _EXTRACTORS:
        raise ParsingError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    extractor = _EXTRACTORS[ext]
    stream = io.BytesIO(file_bytes)
    text = extractor(stream)

    if not text or not text.strip():
        raise ParsingError(
            "No extractable text found. The file may be a scanned image "
            "PDF (needs OCR) or empty."
        )

    return normalise_text(text)
