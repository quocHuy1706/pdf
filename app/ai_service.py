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
    """Sinh câu hỏi trắc nghiệm từ văn bản.

    - AI_PROVIDER=gemini (mặc định): dùng Gemini API.
    - AI_PROVIDER=template: luôn dùng bộ sinh câu hỏi demo (không cần API key).
    - AI_FALLBACK_TO_TEMPLATE=true: nếu Gemini lỗi thì tự động chuyển sang bộ sinh demo
      thay vì báo lỗi cho người dùng.
    """
    quantity = max(1, min(int(quantity), 50))
    clean_text = (text or "").strip()

    if not clean_text:
        raise AIServiceError("Tài liệu chưa có nội dung văn bản để tạo câu hỏi.")

    if AI_PROVIDER == "template":
        return _generate_with_template(clean_text, quantity, difficulty)

    if AI_PROVIDER != "gemini":
        raise AIServiceError("AI_PROVIDER không hợp lệ. Hãy dùng 'gemini' hoặc 'template'.")

    if not GEMINI_API_KEY:
        if AI_FALLBACK_TO_TEMPLATE:
            logger.warning("Chưa có GEMINI_API_KEY, dùng bộ sinh câu hỏi demo (template).")
            return _generate_with_template(clean_text, quantity, difficulty)
        raise AIServiceError(
            "Chưa cấu hình GEMINI_API_KEY trong file .env. Hãy thêm API key rồi khởi động lại server, "
            "hoặc đặt AI_FALLBACK_TO_TEMPLATE=true / AI_PROVIDER=template để dùng bộ sinh câu hỏi demo."
        )

    try:
        return _generate_with_gemini(clean_text, quantity, difficulty)
    except Exception as exc:
        logger.exception("Gemini API tạo câu hỏi thất bại: %s", type(exc).__name__)
        if AI_FALLBACK_TO_TEMPLATE:
            try:
                return _generate_with_template(clean_text, quantity, difficulty)
            except Exception:
                logger.exception("Bộ sinh câu hỏi demo cũng thất bại.")
        raise AIServiceError(
            "Không thể tạo câu hỏi bằng Gemini. Hãy kiểm tra API key, kết nối mạng, hạn mức API và tên model."
        ) from exc

def _generate_with_gemini(text: str, quantity: int, difficulty: str) -> list[dict]:
    from google import genai

    source_text = text[:50000]

    prompt = f"""
Bạn là một giáo viên đại học chuyên biên soạn đề thi trắc nghiệm.

Nhiệm vụ:
Dựa vào nội dung kiến thức được cung cấp bên dưới, hãy tạo {quantity} câu hỏi trắc nghiệm.

Yêu cầu bắt buộc:

- Câu hỏi phải được viết như một đề thi thật.
- Không được sử dụng các cụm từ:
  + "Theo tài liệu"
  + "Trong tài liệu"
  + "Dựa vào tài liệu"
  + "Nội dung nào trong tài liệu"
  + "Thông tin nào trong tài liệu"

- Không đề cập đến nguồn tài liệu trong câu hỏi.
- Người làm bài chỉ nhìn vào câu hỏi và trả lời dựa trên kiến thức.

Ví dụ KHÔNG ĐƯỢC:
❌ Theo tài liệu, mệnh đề trong logic được định nghĩa là gì?
❌ Trong tài liệu, phép nối P AND Q có chân trị bằng 1 khi nào?

Ví dụ ĐƯỢC:
✅ Mệnh đề trong logic được hiểu là gì?
✅ Phép nối P AND Q có chân trị bằng 1 trong trường hợp nào?
✅ Trong logic mệnh đề, phát biểu nào sau đây là đúng?

Yêu cầu nội dung:
- Câu hỏi phải lấy kiến thức trực tiếp từ phần nội dung cung cấp.
- Không tự thêm kiến thức bên ngoài.
- Câu hỏi phải cụ thể, kiểm tra kiến thức thực tế.
- Mức độ câu hỏi: {difficulty}.

Mỗi câu hỏi gồm:
- Nội dung câu hỏi.
- 4 đáp án A, B, C, D.
- Chỉ có 1 đáp án đúng.
- Các đáp án sai phải có tính gây nhiễu hợp lý.
- Có phần giải thích ngắn gọn.

Trả về JSON hợp lệ.

NỘI DUNG KIẾN THỨC:
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
                "temperature": 0.5,
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
        "theo tài liệu",
        "trong tài liệu",
        "dựa vào tài liệu",
        "dựa trên tài liệu",
        "nội dung nào phản ánh đúng",
        "thông tin nào phản ánh đúng",
        "nội dung chính của tài liệu",
    ]

    normalized: list[dict] = []

    for item in raw_questions:
        if not isinstance(item, dict):
            continue

        content = str(item.get("content", "")).strip()

        lower_content = content.lower()

        if any(word in lower_content for word in forbidden_questions):
            continue

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


_STOPWORDS = {
    "và", "của", "là", "các", "một", "những", "có", "được", "cho", "này",
    "trong", "khi", "để", "với", "như", "về", "theo", "không", "đã", "sẽ",
    "hay", "hoặc", "nếu", "thì", "đó", "đây", "vì", "nên", "tại", "từ",
}


def _keywords(sentence: str) -> list[str]:
    """Lấy các từ 'đáng chú ý' trong câu (dài, không phải từ dừng) để làm chỗ trống."""
    words = re.findall(r"[À-Ỹà-ỹA-Za-z0-9]+", sentence)
    return [w for w in words if len(w) >= 5 and w.lower() not in _STOPWORDS]


def _generate_with_template(text: str, quantity: int, difficulty: str) -> list[dict]:
    """Bộ sinh câu hỏi demo, hoạt động offline (không gọi AI).

    Cách hoạt động: chọn các câu đủ dài trong tài liệu, ẩn đi một từ khóa để
    tạo câu hỏi dạng điền khuyết, rồi lấy từ khóa của các câu khác làm phương
    án nhiễu. Chất lượng thấp hơn AI thật nhưng đủ để demo toàn bộ luồng
    (không cần API key), và luôn hoạt động được kể cả khi mất mạng.
    """
    sentences = _sentences(text)
    candidates = [(s, _keywords(s)) for s in sentences]
    candidates = [(s, kws) for s, kws in candidates if kws]

    if len(candidates) < 2:
        raise AIServiceError(
            "Tài liệu quá ngắn hoặc không đủ câu rõ ràng để bộ sinh câu hỏi demo hoạt động. "
            "Hãy dùng tài liệu dài hơn hoặc cấu hình Gemini API."
        )

    rng = random.Random(42)  # seed cố định để kết quả demo ổn định, dễ tái tạo
    rng.shuffle(candidates)

    all_keywords = [kw for _, kws in candidates for kw in kws]

    questions: list[dict] = []
    for sentence, kws in candidates:
        if len(questions) >= quantity:
            break

        answer_word = rng.choice(kws)
        blanked = re.sub(rf"\b{re.escape(answer_word)}\b", "______", sentence, count=1)
        if "______" not in blanked:
            continue

        distractor_pool = [kw for kw in all_keywords if kw.lower() != answer_word.lower()]
        distractor_pool = list(dict.fromkeys(distractor_pool))  # loại trùng, giữ thứ tự
        if len(distractor_pool) < 3:
            continue
        distractors = rng.sample(distractor_pool, 3)

        options = distractors + [answer_word]
        rng.shuffle(options)
        correct_letter = "ABCD"[options.index(answer_word)]

        questions.append(
            {
                "content": f"Điền vào chỗ trống: {blanked}",
                "option_a": options[0],
                "option_b": options[1],
                "option_c": options[2],
                "option_d": options[3],
                "correct_answer": correct_letter,
                "explanation": f"Câu gốc trong tài liệu: \"{sentence.strip()}\".",
            }
        )

    if not questions:
        raise AIServiceError(
            "Bộ sinh câu hỏi demo không tạo được câu hỏi hợp lệ từ tài liệu này. "
            "Hãy thử tài liệu khác hoặc cấu hình Gemini API để có chất lượng tốt hơn."
        )

    return questions