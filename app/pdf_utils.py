from pypdf import PdfReader
from pathlib import Path
import re


def extract_text_from_pdf(path):

    reader = PdfReader(path)

    text = ""

    for page in reader.pages:
        page_text = page.extract_text()

        if page_text:
            text += page_text + "\n\n"

    return text


def get_pdf_metadata(path) -> tuple[int, int]:
    """Trả về (page_count, file_size_bytes) của một file PDF trên đĩa."""
    file_size = Path(path).stat().st_size
    try:
        reader = PdfReader(path)
        page_count = len(reader.pages)
    except Exception:
        page_count = 0
    return page_count, file_size


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 4500) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) + 1 <= max_chars:
            current += ("\n" if current else "") + p
        else:
            if current:
                chunks.append(current)
            current = p

    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]
