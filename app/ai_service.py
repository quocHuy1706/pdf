import json
import logging
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from dotenv import load_dotenv

from .pdf_utils import chunk_text

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

# Văn bản dài hơn ngưỡng này sẽ được chia nhỏ và gọi Gemini song song
# thay vì gửi nguyên khối (nhanh hơn và ít bị cắt bớt nội dung hơn).
CHUNK_CHAR_THRESHOLD = 20_000
CHUNK_MAX_CHARS = 6_000
MAX_PARALLEL_WORKERS = 4


class AIServiceError(RuntimeError):
    """Lỗi an toàn để hiển thị cho người dùng khi dịch vụ AI gặp sự cố."""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [part.strip() for part in parts if len(part.strip()) > 45]


def generate_questions(text: str, quantity: int = 5, difficulty: str = "Trung bình") -> list[dict]:
    """Sinh câu hỏi trắc nghiệm từ văn bản.

    - AI_PROVIDER=gemini (mặc định): dùng Gemini API. Với văn bản dài (> CHUNK_CHAR_THRESHOLD
      ký tự), nội dung sẽ được chia nhỏ và gọi API song song để tăng tốc độ và độ ổn định.
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
        if len(clean_text) > CHUNK_CHAR_THRESHOLD:
            return _generate_with_gemini_chunked(clean_text, quantity, difficulty)
        return _generate_with_gemini(clean_text, quantity, difficulty)
    except Exception as exc:
        logger.exception("Gemini API tạo câu hỏi thất bại: %s", type(exc).__name__)
        if AI_FALLBACK_TO_TEMPLATE:
            try:
                return _generate_with_template(clean_text, quantity, difficulty)
            except Exception:
                logger.exception("Bộ sinh câu hỏi demo cũng thất bại.")
        raise AIServiceError(_classify_gemini_error(exc)) from exc


def _classify_gemini_error(exc: Exception) -> str:
    """Chuyển lỗi kỹ thuật từ Gemini SDK thành thông báo tiếng Việt dễ hiểu."""
    message = str(exc).lower()

    if "429" in message or "resource_exhausted" in message or "quota" in message:
        return (
            "Đã vượt hạn mức (quota) của Gemini API. Vui lòng thử lại sau ít phút "
            "hoặc kiểm tra gói cước của API key."
        )
    if any(k in message for k in ["401", "403", "api key not valid", "api_key_invalid", "permission_denied"]):
        return "GEMINI_API_KEY không hợp lệ hoặc không có quyền truy cập. Hãy kiểm tra lại API key trong file .env."
    if "timeout" in message or "deadline" in message:
        return "Gemini API phản hồi quá lâu (timeout). Hãy thử lại hoặc giảm số lượng câu hỏi."
    if any(k in message for k in ["500", "503", "unavailable", "internal error"]):
        return "Máy chủ Gemini đang gặp sự cố tạm thời (quá tải). Vui lòng thử lại sau ít phút."
    if "not found" in message and "model" in message:
        return f"Model Gemini '{GEMINI_MODEL}' không tồn tại hoặc không khả dụng. Hãy kiểm tra lại GEMINI_MODEL trong .env."

    return "Không thể tạo câu hỏi bằng Gemini. Hãy kiểm tra API key, kết nối mạng, hạn mức API và tên model."


def _generate_with_gemini_chunked(text: str, quantity: int, difficulty: str) -> list[dict]:
    """Chia văn bản dài thành nhiều đoạn và gọi Gemini song song cho từng đoạn,
    sau đó gộp + loại trùng kết quả. Giúp xử lý tài liệu lớn nhanh hơn và ổn định hơn
    so với việc gửi nguyên khối văn bản (dễ bị cắt bớt hoặc vượt giới hạn context)."""
    chunks = chunk_text(text, max_chars=CHUNK_MAX_CHARS)
    num_chunks = len(chunks)

    if num_chunks <= 1:
        return _generate_with_gemini(text, quantity, difficulty)

    base = quantity // num_chunks
    remainder = quantity % num_chunks
    # Phân bổ số câu hỏi cho từng đoạn, đoạn đầu nhận thêm phần dư (nếu có)
    per_chunk_quantities = [base + (1 if i < remainder else 0) for i in range(num_chunks)]
    jobs = [(chunk, q) for chunk, q in zip(chunks, per_chunk_quantities) if q > 0]

    results: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(jobs))) as executor:
        future_to_job = {
            executor.submit(_generate_with_gemini, chunk, q, difficulty): q
            for chunk, q in jobs
        }
        for future in as_completed(future_to_job):
            try:
                results.extend(future.result())
            except Exception as exc:
                errors.append(str(exc))

    # Loại câu hỏi trùng nội dung giữa các đoạn
    seen: set[str] = set()
    unique_results: list[dict] = []
    for q in results:
        key = q["content"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(q)

    if not unique_results:
        detail = "; ".join(errors[:3]) if errors else "không rõ nguyên nhân"
        raise AIServiceError(f"Không thể tạo câu hỏi từ tài liệu lớn này. Chi tiết: {detail}")

    if len(unique_results) < quantity:
        logger.warning(
            "Tài liệu lớn: chỉ tạo được %s/%s câu hỏi hợp lệ sau khi chia nhỏ văn bản (%s đoạn).",
            len(unique_results), quantity, num_chunks,
        )

    return unique_results[:quantity]


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
