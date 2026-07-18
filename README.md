# Web tạo đề thi trắc nghiệm tự động từ PDF bằng Gemini AI

Đây là source code mẫu cho đề tài **Xây dựng hệ thống web tạo đề thi trắc nghiệm tự động từ tài liệu PDF bằng trí tuệ nhân tạo**.

## 1. Chức năng chính

- Đăng ký, đăng nhập, đăng xuất người dùng.
- Tải tài liệu PDF lên hệ thống.
- Trích xuất nội dung văn bản từ PDF.
- Tạo câu hỏi trắc nghiệm tự động bằng Gemini API.
- Chọn số lượng câu hỏi và mức độ khó.
- Tạo phương án A/B/C/D, đáp án đúng và giải thích.
- Chỉnh sửa câu hỏi sau khi AI tạo.
- Lưu bộ đề vào cơ sở dữ liệu SQLite.
- Xuất đề thi ra file PDF hoặc Word.

## 2. Công nghệ sử dụng

- Backend: FastAPI, Python.
- Database: SQLite, SQLAlchemy.
- PDF Processing: pypdf.
- Frontend: Jinja2, HTML, CSS.
- AI: Google Gemini API qua Google Gen AI SDK.
- Export: ReportLab, python-docx.

## 3. Cài đặt lần đầu

```cmd
cd D:\Thực tập viết niên luận\ai_exam_pdf_web\ai_exam_pdf_web
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy /Y .env.example .env
```

## 4. Cấu hình Gemini API

Mở file `.env` và thay dòng sau bằng API key Gemini mới của bạn:

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_new_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash
AI_FALLBACK_TO_TEMPLATE=false
```

Không đưa file `.env` lên GitHub hoặc gửi cho người khác.

## 5. Chạy website

```cmd
cd D:\Thực tập viết niên luận\ai_exam_pdf_web\ai_exam_pdf_web
.venv\Scripts\activate
python -m uvicorn app.main:app --reload
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8000
```

## 6. Cập nhật từ phiên bản cũ

Sau khi thay source code, kích hoạt môi trường ảo và cài lại thư viện:

```cmd
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Sau đó sửa file `.env` theo mục 4 và chạy lại server.

## 7. Chế độ dự phòng

- `AI_FALLBACK_TO_TEMPLATE=false`: hiển thị lỗi nếu Gemini không hoạt động.
- `AI_FALLBACK_TO_TEMPLATE=true`: tự dùng bộ sinh câu hỏi demo khi API lỗi.
- `AI_PROVIDER=template`: luôn sử dụng bộ sinh demo, không gọi Gemini.
