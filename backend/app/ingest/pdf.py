"""Text from PDF quotes. They are digital PDFs (verified), so no OCR; layout mode keeps
table columns on one line, which the model reads far more reliably than reflowed text."""

import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_pdf_text(data: bytes) -> tuple[str, int | None]:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for page in reader.pages:
            raw = page.extract_text(extraction_mode="layout") or ""
            lines = [re.sub(r" {4,}", "   ", ln.rstrip()) for ln in raw.splitlines()]
            pages.append("\n".join(ln for ln in lines if ln.strip()))
        return "\n\n".join(pages).strip(), len(reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError):
        return "", None
