import json
import logging
import os
import random
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
AI_FALLBACK_TO_TEMPLATE = os.getenv("AI_FALLBACK_TO_TEMPLATE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class AIServiceError(RuntimeError):
    """Lỗi an toàn để hiển thị cho người dùng khi dịch vụ AI gặp sự cố."""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [part.strip() for part in parts if len(part.strip()) > 45]


def generate_questions(text: str, quantity: int = 5, difficulty: str = "Trung bình") -> list[dict]:
    """Sinh câu hỏi trắc nghiệm từ văn bản bằng Gemini."""
    quantity = max(1, min(int(quantity), 30))
    clean_text = (text or "").strip()

    if not clean_text:
        raise AIServiceError("Tài liệu chưa có nội dung văn bản để tạo câu hỏi.")

    if AI_PROVIDER != "gemini":
        raise AIServiceError("Hệ thống chỉ hỗ trợ AI_PROVIDER='gemini'.")

    if not GEMINI_API_KEY:
        raise AIServiceError(
            "Chưa cấu hình GEMINI_API_KEY trong file .env. Hãy thêm API key rồi khởi động lại server."
        )

    try:
        return _generate_with_gemini(clean_text, quantity, difficulty)
    except Exception as exc:
        logger.exception("Gemini API tạo câu hỏi thất bại: %s", type(exc).__name__)
        raise AIServiceError(
            "Không thể tạo câu hỏi bằng Gemini. Hãy kiểm tra API key, kết nối mạng, hạn mức API và tên model."
        ) from exc

def _generate_with_gemini(text: str, quantity: int, difficulty: str) -> list[dict]:
    from google import genai

    source_text = text[:50000]

    prompt = f"""
Bạn là giáo viên ra đề thi trắc nghiệm.

Hãy tạo ĐÚNG {quantity} câu hỏi trắc nghiệm bằng tiếng Việt.
Mức độ câu hỏi: {difficulty}.

Chỉ được sử dụng thông tin có trong tài liệu bên dưới.

Yêu cầu bắt buộc:
- Câu hỏi phải hỏi trực tiếp về khái niệm, nội dung, ý chính hoặc thông tin cụ thể trong tài liệu.
- Không tạo câu hỏi chung chung.
- Không hỏi kiểu: "Nội dung nào phản ánh đúng tài liệu?"
- Không hỏi kiểu: "Ý nào sau đây phù hợp nhất?"
- Không hỏi kiểu: "Nội dung chính của tài liệu là gì?"
- Không sử dụng kiến thức bên ngoài tài liệu.
- Mỗi câu có 4 phương án A, B, C, D.
- Chỉ có 1 đáp án đúng.
- Các đáp án sai phải có liên quan nhưng không chính xác.
- Giải thích ngắn gọn vì sao đáp án đúng dựa trên tài liệu.
- Trả về JSON hợp lệ, không thêm chữ giải thích bên ngoài JSON.

TÀI LIỆU:
{source_text}
""".strip()

    question_schema: dict[str, Any] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "option_a": {"type": "string"},
                "option_b": {"type": "string"},
                "option_c": {"type": "string"},
                "option_d": {"type": "string"},
                "correct_answer": {
                    "type": "string",
                    "enum": ["A", "B", "C", "D"],
                },
                "explanation": {"type": "string"},
            },
            "required": [
                "content",
                "option_a",
                "option_b",
                "option_c",
                "option_d",
                "correct_answer",
                "explanation",
            ],
        },
    }

    client = genai.Client(api_key=GEMINI_API_KEY)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": question_schema,
                "temperature": 0.3,
            },
        )

        raw_questions = getattr(response, "parsed", None)

        if raw_questions is None:
            content = (response.text or "").strip()
            if not content:
                raise ValueError("Gemini trả về nội dung rỗng.")
            raw_questions = json.loads(content)

    finally:
        client.close()

    if not isinstance(raw_questions, list):
        raise ValueError("Gemini không trả về danh sách câu hỏi.")

    forbidden_questions = [
        "nội dung nào phản ánh đúng",
        "ý nào sau đây phù hợp nhất",
        "nội dung chính của tài liệu",
        "thông tin nào phản ánh đúng",
        "theo nội dung tài liệu",
    ]

    normalized: list[dict] = []

    for item in raw_questions:
        if not isinstance(item, dict):
            continue

        content = str(item.get("content", "")).strip()

        if any(bad in content.lower() for bad in forbidden_questions):
            continue

        answer_match = re.search(r"[ABCD]", str(item.get("correct_answer", "")).upper())
        correct_answer = answer_match.group(0) if answer_match else ""

        question = {
            "content": content,
            "option_a": str(item.get("option_a", "")).strip(),
            "option_b": str(item.get("option_b", "")).strip(),
            "option_c": str(item.get("option_c", "")).strip(),
            "option_d": str(item.get("option_d", "")).strip(),
            "correct_answer": correct_answer,
            "explanation": str(item.get("explanation", "")).strip(),
        }

        required_values = [
            question["content"],
            question["option_a"],
            question["option_b"],
            question["option_c"],
            question["option_d"],
            question["correct_answer"],
        ]

        if all(required_values):
            normalized.append(question)

        if len(normalized) >= quantity:
            break

    if len(normalized) < quantity:
        raise ValueError(
            f"Gemini chỉ tạo được {len(normalized)}/{quantity} câu hỏi hợp lệ. Hãy thử giảm số lượng câu hỏi hoặc dùng tài liệu dài hơn."
        )

    return normalized