import hashlib
import io
import logging
import os
import re
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bộ dịch glyph font "Symbol" (Adobe Symbol Encoding)
# ---------------------------------------------------------------------------
# Nhiều PDF cũ xuất từ Word (đặc biệt các tài liệu Toán/Logic soạn trước
# 2010) chèn ký hiệu toán học (¬, ∧, ∨, ⇒, ⇔, ∀, ∃, √, Σ, α, β...) bằng font
# "Symbol" thay vì gõ trực tiếp ký tự Unicode. Khi PDF được tạo ra, các công
# cụ xuất PDF thường "double-encode" các glyph này vào vùng Private Use Area
# bằng cách cộng thêm 0xF000 vào mã gốc của font Symbol (đây là quy ước phổ
# biến trên Windows, xem thêm: FontLab / Adobe Glyph docs). Vì vậy một ký tự
# hiển thị là "¬" trong Word có thể được trích xuất ra thành U+F0D8 — một mã
# không có nghĩa gì ngoài ngữ cảnh font Symbol, nên hiển thị thành ô vuông.
#
# Bảng dưới đây lấy từ bảng ánh xạ chính thức "Adobe Symbol Encoding to
# Unicode" (unicode.org/Public/MAPPINGS/VENDORS/ADOBE/symbol.txt), cho phép
# "dịch ngược" các mã U+F0xx này về đúng ký hiệu Unicode chuẩn — chính xác
# tuyệt đối (không phải đoán như OCR) và không ảnh hưởng đến phần văn bản
# tiếng Việt xung quanh (vốn đã được pypdf/PyMuPDF trích xuất đúng).
_SYMBOL_FONT_TABLE = {
    0x20: " ", 0x21: "!", 0x22: "∀", 0x23: "#", 0x24: "∃", 0x25: "%", 0x26: "&", 0x27: "∋",
    0x28: "(", 0x29: ")", 0x2A: "∗", 0x2B: "+", 0x2C: ",", 0x2D: "−", 0x2E: ".", 0x2F: "/",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4", 0x35: "5", 0x36: "6", 0x37: "7",
    0x38: "8", 0x39: "9", 0x3A: ":", 0x3B: ";", 0x3C: "<", 0x3D: "=", 0x3E: ">", 0x3F: "?",
    0x40: "≅", 0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ", 0x47: "Γ",
    0x48: "Η", 0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο",
    0x50: "Π", 0x51: "Θ", 0x52: "Ρ", 0x53: "Σ", 0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω",
    0x58: "Ξ", 0x59: "Ψ", 0x5A: "Ζ", 0x5B: "[", 0x5C: "∴", 0x5D: "]", 0x5E: "⊥", 0x5F: "_",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η",
    0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο",
    0x70: "π", 0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω",
    0x78: "ξ", 0x79: "ψ", 0x7A: "ζ", 0x7B: "{", 0x7C: "|", 0x7D: "}", 0x7E: "∼",
    0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ", 0xA7: "♣", 0xA8: "♦",
    0xA9: "♥", 0xAA: "♠", 0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓",
    0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•",
    0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…", 0xBF: "↵",
    0xC0: "ℵ", 0xC1: "ℑ", 0xC2: "ℜ", 0xC3: "℘", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅",
    0xC7: "∩", 0xC8: "∪", 0xC9: "⊃", 0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆",
    0xCE: "∈", 0xCF: "∉", 0xD0: "∠", 0xD1: "∇",
    0xD5: "∏", 0xD6: "√", 0xD7: "⋅", 0xD8: "¬", 0xD9: "∧", 0xDA: "∨",
    0xDB: "⇔", 0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓",
    0xE0: "◊", 0xE1: "〈", 0xE5: "∑", 0xF1: "〉", 0xF2: "∫", 0xF3: "⌠", 0xF5: "⌡",
}
# Chuyển thành bảng tra theo mã Private Use Area thực tế (0xF000 + mã gốc)
_SYMBOL_FONT_PUA_MAP = {0xF000 + code: ch for code, ch in _SYMBOL_FONT_TABLE.items()}


def _fix_symbol_font_glyphs(text: str) -> str:
    """Dịch các glyph font Symbol bị trích xuất sai thành PUA (U+F020-U+F0FE)
    về đúng ký hiệu Unicode toán học/logic. An toàn để gọi trên mọi văn bản —
    chỉ thay thế đúng những mã nằm trong bảng, giữ nguyên mọi ký tự khác
    (bao gồm toàn bộ dấu tiếng Việt)."""
    if not text:
        return text
    return "".join(_SYMBOL_FONT_PUA_MAP.get(ord(ch), ch) for ch in text)


# ---------------------------------------------------------------------------
# Đánh giá chất lượng trích xuất
# ---------------------------------------------------------------------------
# Sau khi đã dịch glyph font Symbol, các mã PUA còn sót lại (hiếm gặp, thường
# là các glyph trang trí như ngoặc/dấu tích phân kéo dài nhiều dòng, không có
# ký tự Unicode đơn tương ứng) hoặc ký tự thay thế mới thực sự là "lỗi".
_BAD_CHAR_RANGES = [(0xE000, 0xF8FF)]


def _is_bad_char(ch: str) -> bool:
    if ch == "\ufffd":
        return True
    cp = ord(ch)
    if cp < 32 and ch not in "\n\t\r":
        return True
    return any(lo <= cp <= hi for lo, hi in _BAD_CHAR_RANGES)


def _quality_score(text: str) -> float:
    """Điểm chất lượng văn bản trích xuất: càng gần 0 càng tốt (ít ký tự lỗi)."""
    if not text or not text.strip():
        return float("-inf")
    bad = sum(1 for ch in text if _is_bad_char(ch))
    return -bad / max(1, len(text))


def has_extraction_issues(text: str, threshold: float = 0.003) -> bool:
    """True nếu văn bản có tỉ lệ ký tự lỗi/không giải mã được đáng kể
    (ví dụ ký hiệu toán học hoặc dấu tiếng Việt bị mất do font PDF gốc)."""
    return _quality_score(text) < -threshold


class PDFOCRError(RuntimeError):
    """Lỗi khi người dùng chủ động ép buộc OCR (force_ocr=True) nhưng OCR thất bại.
    Khác với luồng tự động (PDF_OCR_FALLBACK), ở đây cần báo lỗi rõ ràng cho
    người dùng thay vì âm thầm quay lại kết quả trích xuất cũ, vì người dùng
    đang chờ đợi kết quả OCR cụ thể."""


# OCR là phương án cuối cùng khi vẫn còn ký tự lỗi sau khi đã dịch glyph
# Symbol (ví dụ font khác không theo chuẩn Symbol, hoặc PDF dạng quét ảnh).
# Yêu cầu cài Tesseract OCR (chương trình hệ thống, không cài được qua pip).
PDF_OCR_FALLBACK = os.getenv("PDF_OCR_FALLBACK", "false").strip().lower() in {"1", "true", "yes", "on"}
PDF_OCR_LANG = os.getenv("PDF_OCR_LANG", "vie+eng").strip()
PDF_OCR_DPI = int(os.getenv("PDF_OCR_DPI", "220"))
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()


def _extract_with_pypdf(path: str) -> str:
    reader = PdfReader(path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n\n"
    return _fix_symbol_font_glyphs(text)


def _extract_with_pymupdf(path: str) -> str:
    import fitz  # PyMuPDF - cài thêm qua `pip install pymupdf`

    text = ""
    with fitz.open(path) as doc:
        for page in doc:
            page_text = page.get_text()
            if page_text:
                text += page_text + "\n\n"
    return _fix_symbol_font_glyphs(text)


def _extract_with_ocr(path: str) -> str:
    """Render từng trang PDF thành ảnh rồi OCR bằng Tesseract.

    Không phụ thuộc bảng mã (CMap) của font nhúng trong PDF, nên là phương án
    cuối khi cả trích xuất text lẫn bảng dịch font Symbol đều không xử lý
    được (ví dụ font ký hiệu không theo chuẩn Symbol, hoặc PDF dạng quét
    ảnh). Cần cài chương trình Tesseract OCR ở tầng hệ điều hành (xem
    README).
    """
    import fitz
    import pytesseract
    from PIL import Image

    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    text_parts = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=PDF_OCR_DPI)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            page_text = pytesseract.image_to_string(img, lang=PDF_OCR_LANG)
            if page_text:
                text_parts.append(page_text)
    return "\n\n".join(text_parts)


def extract_text_from_pdf(path: str, force_ocr: bool = False) -> str:
    """Trích xuất văn bản từ PDF.

    1. Thử cả pypdf và PyMuPDF, mỗi kết quả đều được dịch qua bảng font
       Symbol (`_fix_symbol_font_glyphs`) để khôi phục đúng ký hiệu toán học
       (¬, ∧, ∨, ⇒, ⇔, √, Σ...) — đây là bước sửa lỗi chính xác nhất vì dựa
       trên bảng mã chuẩn, không phải suy đoán. Sau đó chọn kết quả có tỉ lệ
       ký tự lỗi thấp hơn.
    2. Nếu kết quả vẫn còn nhiều ký tự lỗi (hoặc `force_ocr=True`) và đã bật
       PDF_OCR_FALLBACK, thử OCR toàn bộ tài liệu — dùng cho trường hợp hiếm
       hơn: font ký hiệu không theo chuẩn Symbol, hoặc PDF dạng quét ảnh.
    """
    pypdf_text = _extract_with_pypdf(path)

    pymupdf_text = ""
    try:
        pymupdf_text = _extract_with_pymupdf(path)
    except ImportError:
        logger.info("Chưa cài PyMuPDF, chỉ dùng pypdf để trích xuất.")
    except Exception:
        logger.exception("PyMuPDF trích xuất lỗi, dùng kết quả pypdf.")

    best_text = pypdf_text
    if pymupdf_text and _quality_score(pymupdf_text) >= _quality_score(best_text):
        best_text = pymupdf_text

    if (PDF_OCR_FALLBACK or force_ocr) and (force_ocr or has_extraction_issues(best_text)):
        try:
            ocr_text = _extract_with_ocr(path)
            if ocr_text and (force_ocr or _quality_score(ocr_text) > _quality_score(best_text)):
                logger.info("Dùng kết quả OCR thay cho trích xuất PDF gốc (chất lượng tốt hơn).")
                return ocr_text
            if force_ocr and not ocr_text:
                raise RuntimeError("OCR không nhận diện được nội dung nào từ tài liệu.")
        except ImportError as exc:
            message = (
                "Chưa cài đủ thư viện cho OCR (pytesseract/Pillow). "
                "Chạy `pip install -r requirements.txt` rồi thử lại."
            )
            if force_ocr:
                raise PDFOCRError(message) from exc
            logger.info(message)
        except Exception as exc:
            message = (
                "Không thể chạy OCR — kiểm tra đã cài chương trình Tesseract OCR trên máy chủ "
                "chưa (xem README), hoặc đường dẫn TESSERACT_CMD trong .env có đúng không. "
                f"Chi tiết: {exc}"
            )
            if force_ocr:
                raise PDFOCRError(message) from exc
            logger.exception("OCR fallback thất bại, dùng kết quả trích xuất PDF gốc.")

    return best_text


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


def calculate_file_hash(content: bytes) -> str:
    """
    Tính SHA-256 của nội dung file.
    Cùng một file sẽ luôn tạo ra cùng một hash.
    """
    return hashlib.sha256(content).hexdigest()