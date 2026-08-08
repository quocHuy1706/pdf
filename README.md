# 📚 ExamPDF AI

> Hệ thống web tạo đề thi trắc nghiệm tự động từ tài liệu PDF bằng Trí tuệ nhân tạo (Gemini AI).

ExamPDF AI là hệ thống hỗ trợ giáo viên, sinh viên và người học tự động tạo đề thi trắc nghiệm từ tài liệu PDF. Hệ thống sử dụng Google Gemini AI để phân tích nội dung, sinh câu hỏi, đáp án và lời giải, giúp tiết kiệm thời gian xây dựng ngân hàng câu hỏi.

---

# 🚀 Tính năng nổi bật

## 👤 Quản lý người dùng

- Đăng ký tài khoản
- Đăng nhập
- Đăng xuất
- Quản lý thông tin cá nhân
- Phân quyền User / Admin

---

## 📄 Quản lý tài liệu

- Upload tài liệu PDF
- Trích xuất văn bản tự động
- Lưu lịch sử tài liệu
- Quản lý nhiều tài liệu
- Xem chi tiết từng tài liệu

---

## 🤖 Tạo đề thi bằng AI

- Phân tích nội dung PDF bằng Gemini AI
- Sinh câu hỏi trắc nghiệm tự động
- Sinh đáp án A/B/C/D
- Xác định đáp án đúng
- Sinh lời giải
- Điều chỉnh số lượng câu hỏi
- Điều chỉnh độ khó

---

## 📝 Quản lý đề thi

- Lưu đề thi
- Xem chi tiết đề
- Chỉnh sửa câu hỏi
- Xuất đề thi
- Lưu lịch sử tạo đề

---

## 📊 Dashboard

- Danh sách tài liệu
- Danh sách đề thi
- Thống kê người dùng
- Quản lý hoạt động

---

# 🏗️ Kiến trúc hệ thống

```
React (Frontend)

↓

Cloudflare Pages

↓

FastAPI REST API

↓

Gemini AI

↓

MySQL

↓

Cloudflare R2 (định hướng)
```

---

# 🛠 Công nghệ sử dụng

## Backend

- Python
- FastAPI
- SQLAlchemy
- PyMySQL
- Uvicorn

## Frontend

- React
- Vite
- Axios
- React Router

## Database

- MySQL 8

## AI

- Google Gemini API

## Storage

- Local Storage (hiện tại)
- Cloudflare R2 (định hướng)

---

# 📁 Cấu trúc dự án

```
pdf/

│

├── backend/

│ ├── app/

│ │ ├── main.py

│ │ ├── database.py

│ │ ├── models.py

│ │ ├── ai_service.py

│ │ ├── pdf_utils.py

│ │ ├── security.py

│ │ ├── admin.py

│ │ └── routes/

│

├── frontend/

│ ├── src/

│ ├── public/

│ └── package.json

│

├── uploads/

├── exports/

│

├── database_mysql.sql

├── requirements.txt

└── README.md
```

---

# ⚙️ Yêu cầu hệ thống

- Python 3.12+
- NodeJS 20+
- MySQL 8+
- Google Gemini API Key

---

# 📦 Cài đặt Backend

```bash
git clone https://github.com/quocHuy1706/pdf.git

cd pdf

python -m venv .venv
```

Windows

```bash
.venv\Scripts\activate
```

Linux

```bash
source .venv/bin/activate
```

Cài thư viện

```bash
pip install -r requirements.txt
```

---

# 🗄️ Tạo Database

Import

```
database_mysql.sql
```

vào MySQL.

---

# ⚙️ Cấu hình môi trường

Tạo file

```
.env
```

```env
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/pdf_web

AI_PROVIDER=gemini

GEMINI_API_KEY=YOUR_API_KEY

GEMINI_MODEL=gemini-2.5-flash

SECRET_KEY=CHANGE_ME

ENVIRONMENT=development
```

---

# ▶️ Chạy Backend

```bash
python -m uvicorn app.main:app --reload
```

API

```
http://127.0.0.1:8000
```

Swagger

```
http://127.0.0.1:8000/docs
```

---

# 🌐 Chạy Frontend

```bash
cd frontend

npm install

npm run dev
```

Frontend

```
http://localhost:5173
```

---

# 🔄 Quy trình hoạt động

```
Đăng nhập

↓

Upload PDF

↓

Trích xuất văn bản

↓

Gemini AI

↓

Sinh câu hỏi

↓

Sinh đáp án

↓

Sinh lời giải

↓

Lưu Database

↓

Xuất đề thi
```

---

# 🔒 Bảo mật

- Password Hashing
- Session Authentication
- SQLAlchemy ORM
- Chống SQL Injection
- Quản lý phân quyền
- Bảo vệ API

---

# 📌 Định hướng phát triển

- Chat với PDF
- Flashcard AI
- Mindmap AI
- Tóm tắt tài liệu
- Bloom Taxonomy
- AI Quality Score
- AI Difficulty Slider
- AI Duplicate Detection
- OCR thông minh
- Cloudflare R2
- Đa ngôn ngữ
- Mobile Responsive
- Progressive Web App (PWA)

---

# 🚀 Triển khai

Frontend

- Cloudflare Pages

Backend

- Render hoặc Railway

Database

- MySQL

Storage

- Cloudflare R2

---

# 👨‍💻 Tác giả

**Quốc Huy**

GitHub:

https://github.com/quocHuy1706

---

# ⭐ Nếu thấy dự án hữu ích

Hãy để lại một ⭐ trên GitHub để ủng hộ dự án.
