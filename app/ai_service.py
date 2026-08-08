import json
import logging
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any

from dotenv import load_dotenv

from .pdf_utils import chunk_text

load_dotenv()

logger = logging.getLogger(__name__)

AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()
AI_FALLBACK_TO_TEMPLATE = os.getenv("AI_FALLBACK_TO_TEMPLATE", "false").strip().lower() in {
    "1", "true", "yes", "on",
}

MAX_QUESTIONS = 50
GEMINI_BATCH_SIZE = 10
MAX_BATCH_RETRIES = 4

CHUNK_CHAR_THRESHOLD = 20_000
CHUNK_MAX_CHARS = 6_000
MAX_PARALLEL_WORKERS = 4

QUESTION_SIMILARITY_THRESHOLD = 0.88


class AIServiceError(RuntimeError):
    """Lỗi an toàn để hiển thị cho người dùng khi dịch vụ AI gặp sự cố."""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [part.strip() for part in parts if len(part.strip()) > 45]


def _normalize_question_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\sÀ-ỹ]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_similar_question(
    content: str,
    existing_questions: list[dict],
    threshold: float = QUESTION_SIMILARITY_THRESHOLD,
) -> bool:
    normalized = _normalize_question_text(content)

    if not normalized:
        return True

    for question in existing_questions:
        existing = _normalize_question_text(question.get("content", ""))

        if not existing:
            continue

        if normalized == existing:
            return True

        similarity = SequenceMatcher(None, normalized, existing).ratio()

        if similarity >= threshold:
            return True

    return False


def generate_questions(text: str, quantity: int = 5, difficulty: str = "Trung bình") -> list[dict]:
    """Sinh câu hỏi trắc nghiệm từ văn bản.

    - Tối đa 50 câu.
    - Gemini tạo theo nhiều batch nhỏ, mỗi batch tối đa 10 câu.
    - 60% câu hỏi kiến thức trực tiếp, 40% câu hỏi vận dụng.
    - Văn bản dài được chia chunk và xử lý song song.
    - AI_PROVIDER=template: dùng bộ sinh demo offline.
    """

    quantity = max(1, min(int(quantity), MAX_QUESTIONS))
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
    """Chia tài liệu dài thành nhiều đoạn, tạo câu hỏi song song rồi gộp và loại trùng."""

    quantity = max(1, min(int(quantity), MAX_QUESTIONS))

    chunks = chunk_text(text, max_chars=CHUNK_MAX_CHARS)
    num_chunks = len(chunks)

    if num_chunks <= 1:
        return _generate_with_gemini(text, quantity, difficulty)

    useful_chunk_count = min(num_chunks, quantity)

    if useful_chunk_count < num_chunks:
        if useful_chunk_count == 1:
            chunks = [chunks[0]]
        else:
            chunks = [
                chunks[round(i * (num_chunks - 1) / (useful_chunk_count - 1))]
                for i in range(useful_chunk_count)
            ]

        num_chunks = len(chunks)

    base = quantity // num_chunks
    remainder = quantity % num_chunks

    per_chunk_quantities = [
        base + (1 if i < remainder else 0)
        for i in range(num_chunks)
    ]

    jobs = [
        (chunk, q)
        for chunk, q in zip(chunks, per_chunk_quantities)
        if q > 0
    ]

    results: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_WORKERS, len(jobs))) as executor:
        future_to_job = {
            executor.submit(_generate_with_gemini, chunk, q, difficulty): (chunk, q)
            for chunk, q in jobs
        }

        for future in as_completed(future_to_job):
            try:
                batch_result = future.result()

                for question in batch_result:
                    if _is_similar_question(question.get("content", ""), results):
                        continue

                    results.append(question)

            except Exception as exc:
                errors.append(str(exc))

    if not results:
        detail = "; ".join(errors[:3]) if errors else "không rõ nguyên nhân"
        raise AIServiceError(f"Không thể tạo câu hỏi từ tài liệu lớn này. Chi tiết: {detail}")

    total_direct = round(quantity * 0.6)
    total_application = quantity - total_direct

    direct_questions = [q for q in results if q.get("question_type") == "document"]
    application_questions = [q for q in results if q.get("question_type") == "application"]

    retries = 0

    while (
        len(direct_questions) < total_direct
        or len(application_questions) < total_application
    ) and retries < MAX_BATCH_RETRIES:

        retries += 1

        missing_direct = max(0, total_direct - len(direct_questions))
        missing_application = max(0, total_application - len(application_questions))
        missing_total = missing_direct + missing_application

        if missing_total <= 0:
            break

        refill_chunk = chunks[(retries - 1) % len(chunks)]
        batch_size = min(missing_total, GEMINI_BATCH_SIZE)

        batch_direct = min(missing_direct, batch_size)
        batch_application = min(missing_application, batch_size - batch_direct)

        refill = _generate_gemini_batch(
            text=refill_chunk,
            quantity=batch_direct + batch_application,
            difficulty=difficulty,
            direct_count=batch_direct,
            application_count=batch_application,
            previous_questions=results,
        )

        for question in refill:
            if _is_similar_question(question.get("content", ""), results):
                continue

            question_type = question.get("question_type")

            if question_type == "document" and len(direct_questions) < total_direct:
                direct_questions.append(question)
                results.append(question)

            elif question_type == "application" and len(application_questions) < total_application:
                application_questions.append(question)
                results.append(question)

    if len(direct_questions) < total_direct or len(application_questions) < total_application:
        raise AIServiceError(
            "Không thể tạo đủ đề theo đúng tỷ lệ 60/40. "
            f"Đã tạo {len(direct_questions)}/{total_direct} câu kiến thức "
            f"và {len(application_questions)}/{total_application} câu vận dụng. "
            "Hãy thử giảm số lượng câu hỏi hoặc sử dụng tài liệu có nội dung phong phú hơn."
        )

    return (
        direct_questions[:total_direct]
        + application_questions[:total_application]
    )[:quantity]


def _generate_with_gemini(text: str, quantity: int, difficulty: str) -> list[dict]:
    """Sinh câu hỏi bằng nhiều lần gọi Gemini, mỗi lần tối đa 10 câu."""

    quantity = max(1, min(int(quantity), MAX_QUESTIONS))

    total_direct = round(quantity * 0.6)
    total_application = quantity - total_direct

    questions: list[dict] = []

    direct_created = 0
    application_created = 0
    retry_round = 0

    while len(questions) < quantity:
        remaining_direct = max(0, total_direct - direct_created)
        remaining_application = max(0, total_application - application_created)
        remaining_total = remaining_direct + remaining_application

        if remaining_total <= 0:
            break

        batch_size = min(GEMINI_BATCH_SIZE, remaining_total)

        batch_direct = round(batch_size * remaining_direct / remaining_total)
        batch_direct = min(batch_direct, remaining_direct, batch_size)

        batch_application = batch_size - batch_direct

        if batch_application > remaining_application:
            excess = batch_application - remaining_application
            batch_application = remaining_application
            batch_direct = min(remaining_direct, batch_direct + excess)

        if batch_direct > remaining_direct:
            excess = batch_direct - remaining_direct
            batch_direct = remaining_direct
            batch_application = min(remaining_application, batch_application + excess)

        batch_quantity = batch_direct + batch_application

        if batch_quantity <= 0:
            break

        batch_questions = _generate_gemini_batch(
            text=text,
            quantity=batch_quantity,
            difficulty=difficulty,
            direct_count=batch_direct,
            application_count=batch_application,
            previous_questions=questions,
        )

        added = 0

        for question in batch_questions:
            question_type = question.get("question_type")

            if question_type == "document" and direct_created >= total_direct:
                continue

            if question_type == "application" and application_created >= total_application:
                continue

            if _is_similar_question(question.get("content", ""), questions):
                continue

            questions.append(question)
            added += 1

            if question_type == "document":
                direct_created += 1
            elif question_type == "application":
                application_created += 1

            if len(questions) >= quantity:
                break

        if added == 0:
            retry_round += 1

            if retry_round >= MAX_BATCH_RETRIES:
                break
        else:
            retry_round = 0

    if (
        len(questions) < quantity
        or direct_created < total_direct
        or application_created < total_application
    ):
        raise ValueError(
            "Gemini không thể tạo đủ đề sau nhiều lần thử. "
            f"Đã tạo {len(questions)}/{quantity} câu. "
            f"Kiến thức: {direct_created}/{total_direct}. "
            f"Vận dụng: {application_created}/{total_application}. "
            "Hãy thử giảm số lượng câu hỏi hoặc sử dụng tài liệu dài hơn."
        )

    return questions[:quantity]


def _generate_gemini_batch(
    text: str,
    quantity: int,
    difficulty: str,
    direct_count: int,
    application_count: int,
    previous_questions: list[dict] | None = None,
) -> list[dict]:
    """Một lần gọi Gemini, tối đa 10 câu."""

    from google import genai

    quantity = max(1, min(int(quantity), GEMINI_BATCH_SIZE))
    previous_questions = previous_questions or []

    source_text = (text or "")[:50000]
    difficulty_normalized = difficulty.strip().lower()

    if difficulty_normalized in ["dễ", "easy"]:
        application_instruction = """
- Câu vận dụng ở mức cơ bản.
- Chỉ cần 1 bước suy luận hoặc áp dụng trực tiếp công thức/quy tắc/khái niệm.
- Tình huống ngắn, quen thuộc, rõ ràng.
- Không đánh đố.
"""

    elif difficulty_normalized in ["khó", "hard"]:
        application_instruction = """
- Câu vận dụng ở mức nâng cao.
- Có thể yêu cầu phân tích tình huống mới.
- Có thể kết hợp 2 hoặc nhiều khái niệm liên quan.
- Có thể cần nhiều bước suy luận.
- Phương án nhiễu phải phản ánh lỗi suy luận hợp lý.
"""

    else:
        application_instruction = """
- Câu vận dụng ở mức trung bình.
- Áp dụng kiến thức vào tình huống hoặc ví dụ mới.
- Có thể cần 1 đến 2 bước suy luận.
- Có thể kết hợp các kiến thức liên quan.
"""

    previous_contents = []

    for question in previous_questions[-40:]:
        content = str(question.get("content", "")).strip()

        if content:
            previous_contents.append(f"- {content}")

    previous_text = "\n".join(previous_contents) if previous_contents else "Chưa có câu hỏi nào được tạo trước đó."

    prompt = f"""
Bạn là một giáo viên đại học chuyên biên soạn đề thi trắc nghiệm.

Nhiệm vụ:
Tạo CHÍNH XÁC {quantity} câu hỏi trắc nghiệm.

Mức độ đề thi:
{difficulty}

==================================================
CƠ CẤU ĐỀ
==================================================

Tổng số câu: {quantity}

Câu kiến thức trực tiếp:
- Chính xác {direct_count} câu.
- question_type="document".
- Đáp án phải được hỗ trợ trực tiếp bởi nội dung cung cấp.
- Có thể kiểm tra khái niệm, định nghĩa, đặc điểm, nguyên lý,
  quy trình, công thức, mối quan hệ và kiến thức cốt lõi.
- Không sao chép nguyên văn máy móc.
- Ưu tiên hiểu bản chất.

Câu vận dụng:
- Chính xác {application_count} câu.
- question_type="application".
- Kiến thức dùng để giải phải xuất phát từ nội dung cung cấp.
- Được phép tạo tình huống, ví dụ, dữ kiện hoặc số liệu mới.
- Không yêu cầu kiến thức chuyên môn hoàn toàn nằm ngoài nội dung.

Yêu cầu vận dụng theo mức độ:

{application_instruction}

Nếu có công thức:
- Có thể thay số liệu.
- Có thể yêu cầu tính toán.
- Có thể hỏi sự thay đổi của các đại lượng.

Nếu có quy trình:
- Có thể tạo tình huống xử lý.
- Có thể yêu cầu phát hiện bước sai.

Nếu có nguyên lý hoặc lý thuyết:
- Có thể tạo tình huống thực tế.
- Có thể yêu cầu lựa chọn nguyên lý phù hợp.
- Có thể yêu cầu phân tích nguyên nhân hoặc kết quả.

==================================================
CÁCH VIẾT CÂU HỎI
==================================================

Câu hỏi phải giống đề thi thật.

KHÔNG sử dụng các cụm từ:

- "Theo tài liệu"
- "Trong tài liệu"
- "Dựa vào tài liệu"
- "Dựa trên tài liệu"
- "Nội dung nào trong tài liệu"
- "Thông tin nào trong tài liệu"

Không đề cập đến nguồn tài liệu trong câu hỏi.

Ví dụ sai:
"Theo tài liệu, mệnh đề là gì?"

Ví dụ đúng:
"Mệnh đề trong logic được hiểu là gì?"

==================================================
ĐÁP ÁN
==================================================

Mỗi câu phải có:
- content
- option_a
- option_b
- option_c
- option_d
- correct_answer
- explanation
- question_type

Yêu cầu:
- Đúng 4 phương án A/B/C/D.
- Chỉ có 1 đáp án đúng nhất.
- Các đáp án sai phải gây nhiễu hợp lý.
- Không sử dụng "Tất cả các đáp án trên".
- Không sử dụng "Cả A và B".
- Các phương án nên có độ dài tương đối cân bằng.

==================================================
CHỐNG TRÙNG
==================================================

Các câu sau đã được tạo:

{previous_text}

Không được:
- tạo lại cùng câu;
- chỉ đổi vài từ rồi hỏi lại cùng một ý;
- tạo câu có nội dung gần giống các câu đã có.

==================================================
PHÂN BỐ KIẾN THỨC
==================================================

- Không tập trung quá nhiều câu vào cùng một đoạn.
- Nếu có nhiều mục hoặc chương, ưu tiên phủ đều.
- Không tạo nhiều câu kiểm tra cùng một chi tiết nhỏ.

==================================================
TỰ KIỂM TRA
==================================================

Trước khi trả kết quả:
1. Có đúng {quantity} câu.
2. Có đúng {direct_count} câu document.
3. Có đúng {application_count} câu application.
4. Không có câu hỏi trùng ý.
5. Mỗi câu chỉ có một đáp án đúng.
6. Độ khó phù hợp mức "{difficulty}".
7. Câu vận dụng vẫn giải được từ kiến thức cung cấp.

==================================================
NỘI DUNG KIẾN THỨC
==================================================

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
                "question_type": {
                    "type": "string",
                    "enum": ["document", "application"],
                },
            },
            "required": [
                "content",
                "option_a",
                "option_b",
                "option_c",
                "option_d",
                "correct_answer",
                "explanation",
                "question_type",
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
                "temperature": 0.55,
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

    batch_document_count = 0
    batch_application_count = 0

    for item in raw_questions:
        if not isinstance(item, dict):
            continue

        content = str(item.get("content", "")).strip()
        lower_content = content.lower()

        if any(word in lower_content for word in forbidden_questions):
            continue

        answer_match = re.search(r"[ABCD]", str(item.get("correct_answer", "")).upper())
        correct_answer = answer_match.group(0) if answer_match else ""

        question_type = str(item.get("question_type", "")).strip().lower()

        if question_type not in {"document", "application"}:
            continue

        question = {
            "content": content,
            "option_a": str(item.get("option_a", "")).strip(),
            "option_b": str(item.get("option_b", "")).strip(),
            "option_c": str(item.get("option_c", "")).strip(),
            "option_d": str(item.get("option_d", "")).strip(),
            "correct_answer": correct_answer,
            "explanation": str(item.get("explanation", "")).strip(),
            "question_type": question_type,
        }

        required_values = [
            question["content"],
            question["option_a"],
            question["option_b"],
            question["option_c"],
            question["option_d"],
            question["correct_answer"],
        ]

        if not all(required_values):
            continue

        if _is_similar_question(content, previous_questions + normalized):
            continue

        if question_type == "document":
            if batch_document_count >= direct_count:
                continue

            batch_document_count += 1

        elif question_type == "application":
            if batch_application_count >= application_count:
                continue

            batch_application_count += 1

        normalized.append(question)

    return normalized


_STOPWORDS = {
    "và", "của", "là", "các", "một", "những", "có", "được", "cho", "này",
    "trong", "khi", "để", "với", "như", "về", "theo", "không", "đã", "sẽ",
    "hay", "hoặc", "nếu", "thì", "đó", "đây", "vì", "nên", "tại", "từ",
}


def _keywords(sentence: str) -> list[str]:
    """Lấy các từ đáng chú ý trong câu để làm chỗ trống."""

    words = re.findall(r"[À-Ỹà-ỹA-Za-z0-9]+", sentence)
    return [word for word in words if len(word) >= 5 and word.lower() not in _STOPWORDS]


def _generate_with_template(text: str, quantity: int, difficulty: str) -> list[dict]:
    """Bộ sinh câu hỏi demo offline, không gọi Gemini."""

    quantity = max(1, min(int(quantity), MAX_QUESTIONS))

    sentences = _sentences(text)

    candidates = [(sentence, _keywords(sentence)) for sentence in sentences]
    candidates = [(sentence, keywords) for sentence, keywords in candidates if keywords]

    if len(candidates) < 2:
        raise AIServiceError(
            "Tài liệu quá ngắn hoặc không đủ câu rõ ràng để bộ sinh câu hỏi demo hoạt động. "
            "Hãy dùng tài liệu dài hơn hoặc cấu hình Gemini API."
        )

    rng = random.Random(42)
    rng.shuffle(candidates)

    all_keywords = [keyword for _, keywords in candidates for keyword in keywords]

    questions: list[dict] = []

    for sentence, keywords in candidates:
        if len(questions) >= quantity:
            break

        answer_word = rng.choice(keywords)

        blanked = re.sub(
            rf"\b{re.escape(answer_word)}\b",
            "______",
            sentence,
            count=1,
        )

        if "______" not in blanked:
            continue

        distractor_pool = [
            keyword
            for keyword in all_keywords
            if keyword.lower() != answer_word.lower()
        ]

        distractor_pool = list(dict.fromkeys(distractor_pool))

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
                "explanation": f'Câu gốc trong tài liệu: "{sentence.strip()}".',
                "question_type": "document",
            }
        )

    if not questions:
        raise AIServiceError(
            "Bộ sinh câu hỏi demo không tạo được câu hỏi hợp lệ từ tài liệu này. "
            "Hãy thử tài liệu khác hoặc cấu hình Gemini API."
        )

    return questions