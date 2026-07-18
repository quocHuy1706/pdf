from pypdf import PdfReader
from pathlib import Path
import re


def extract_text_from_pdf(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError("Không tìm thấy file PDF.")

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)

    raw_text = "\n".join(pages)
    return clean_text(raw_text)


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
