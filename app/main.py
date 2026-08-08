from fastapi import FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
import os
import hashlib
from . import admin
from .models import ActivityLog
from dotenv import load_dotenv
from .database import Base, engine, get_db
from .models import User, Document, Exam, Question
from .security import (
    hash_password,
    verify_password,
    update_password,
    register_failed_login,
    reset_failed_login,
    is_login_locked,
)
from .pdf_utils import extract_text_from_pdf, get_pdf_metadata, has_extraction_issues
from .ai_service import AIServiceError, generate_questions
from .export_utils import export_exam_docx, export_exam_pdf

load_dotenv()

APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "change-this-secret-key")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
EXPORT_DIR = os.getenv("EXPORT_DIR", "exports")

Path(UPLOAD_DIR).mkdir(exist_ok=True)
Path(EXPORT_DIR).mkdir(exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Exam PDF Web")
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY, https_only=False, same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.include_router(admin.router)


def current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Bạn cần đăng nhập.")
    return user


def log_action(db: Session, user_id: int, action: str):
    log_entry = ActivityLog(user_id=user_id, action=action)
    db.add(log_entry)
    db.commit()


@app.exception_handler(401)
async def unauthorized_handler(request: Request, exc: HTTPException):
    # Yêu cầu JSON (gọi từ JS/API) thì trả JSON, còn lại thì chuyển hướng sang trang đăng nhập
    if request.headers.get("accept", "").find("application/json") != -1 and "text/html" not in request.headers.get("accept", ""):
        return JSONResponse(status_code=401, content={"detail": exc.detail})
    return RedirectResponse(url="/login", status_code=303)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc: HTTPException):
    if "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(
            content=f"<h1>403 - {exc.detail}</h1><p><a href='/dashboard'>Quay lại</a></p>",
            status_code=403,
        )
    return JSONResponse(status_code=403, content={"detail": exc.detail})


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return templates.TemplateResponse("register.html", {"request": request, "user": user, "error": None})


@app.post("/register")
def register(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    exists = db.query(User).filter(User.email == email_norm).first()
    if exists:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Email đã tồn tại."})

    if len(password) < 6:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Mật khẩu phải có ít nhất 6 ký tự."})

    user = User(full_name=full_name.strip(), email=email_norm, password_hash=hash_password(password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    log_action(db, user.id, "Đăng ký tài khoản")
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return templates.TemplateResponse("login.html", {"request": request, "user": user, "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    email_norm = email.strip().lower()

    if is_login_locked(email_norm):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "user": None, "error": "Tài khoản tạm khóa do đăng nhập sai quá nhiều lần. Hãy thử lại sau."},
        )

    user = db.query(User).filter(User.email == email_norm).first()
    if not user or not verify_password(password, user.password_hash):
        register_failed_login(email_norm)
        return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": "Email hoặc mật khẩu không đúng."})

    reset_failed_login(email_norm)
    request.session["user_id"] = user.id
    log_action(db, user.id, "Đăng nhập")
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user:
        log_action(db, user.id, "Đăng xuất")
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    documents = db.query(Document).filter(Document.user_id == user.id).order_by(Document.created_at.desc()).all()
    all_exams = db.query(Exam).filter(Exam.user_id == user.id).order_by(Exam.created_at.desc()).all()
    exams = all_exams[:5]
    total_questions = sum(len(e.questions) for e in all_exams)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "documents": documents,
            "exams": exams,
            "stats": {
                "documents": len(documents),
                "exams": len(all_exams),
                "questions": total_questions,
            },
        },
    )


@app.get("/activity", response_class=HTMLResponse)
def activity_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user.id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse("activity.html", {"request": request, "user": user, "logs": logs})


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("account.html", {"request": request, "user": user, "error": None, "success": None})


@app.post("/account")
def update_account(
    request: Request,
    full_name: str = Form(...),
    current_password: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    user.full_name = full_name.strip() or user.full_name

    if new_password:
        if not verify_password(current_password, user.password_hash):
            db.commit()
            return templates.TemplateResponse(
                "account.html",
                {"request": request, "user": user, "error": "Mật khẩu hiện tại không đúng.", "success": None},
            )
        if len(new_password) < 6:
            return templates.TemplateResponse(
                "account.html",
                {"request": request, "user": user, "error": "Mật khẩu mới phải có ít nhất 6 ký tự.", "success": None},
            )
        update_password(db, user, new_password)
        log_action(db, user.id, "Đổi mật khẩu")
    else:
        db.commit()

    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "error": None, "success": "Đã cập nhật thông tin tài khoản."},
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": None})


@app.post("/upload")
async def upload_pdf(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # 1. Kiểm tra định dạng PDF
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "user": user,
                "error": "Vui lòng chọn file PDF.",
            },
        )

    # 2. Đọc toàn bộ nội dung file trước
    file_content = await file.read()

    if not file_content:
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "user": user,
                "error": "File PDF rỗng.",
            },
        )

    # 3. Tính SHA-256
    file_hash = hashlib.sha256(file_content).hexdigest()

    # 4. Kiểm tra user này đã upload đúng file này chưa
    existing_document = (
        db.query(Document)
        .filter(
            Document.user_id == user.id,
            Document.file_hash == file_hash,
        )
        .first()
    )

    # 5. Nếu đã tồn tại thì dùng lại tài liệu cũ
    if existing_document:
        log_action(
            db,
            user.id,
            f"Mở lại tài liệu đã tồn tại: {existing_document.title}",
        )

        return RedirectResponse(
            url=f"/documents/{existing_document.id}",
            status_code=303,
        )

    # 6. File chưa tồn tại -> mới lưu vào uploads
    safe_filename = (
        f"user_{user.id}_"
        f"{file_hash[:12]}_"
        f"{Path(file.filename).name.replace(' ', '_')}"
    )

    file_path = Path(UPLOAD_DIR) / safe_filename

    try:
        with file_path.open("wb") as buffer:
            buffer.write(file_content)

        extracted_text = extract_text_from_pdf(str(file_path))

        page_count, file_size = get_pdf_metadata(
            str(file_path)
        )

    except Exception as exc:
        file_path.unlink(missing_ok=True)

        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "user": user,
                "error": f"Không đọc được PDF: {exc}",
            },
        )

    # 7. Tạo document mới
    document = Document(
        user_id=user.id,
        title=title.strip() or file.filename,
        file_path=str(file_path),
        extracted_text=extracted_text,
        file_size=file_size,
        page_count=page_count,
        extraction_warning=has_extraction_issues(
            extracted_text
        ),
        file_hash=file_hash,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    log_action(
        db,
        user.id,
        f"Tải lên tài liệu: {document.title}",
    )

    return RedirectResponse(
        url=f"/documents/{document.id}",
        status_code=303,
    )


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(document_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")
    exams = db.query(Exam).filter(Exam.document_id == document.id, Exam.user_id == user.id).order_by(Exam.created_at.desc()).all()
    preview_text = (document.extracted_text or "")[:3000]
    return templates.TemplateResponse("document_detail.html", {"request": request, "user": user, "document": document, "preview_text": preview_text, "exams": exams})


@app.post("/documents/{document_id}/delete")
def delete_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")

    file_path = Path(document.file_path)
    title = document.title
    db.delete(document)
    db.commit()
    file_path.unlink(missing_ok=True)

    log_action(db, user.id, f"Xóa tài liệu: {title}")
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/documents/{document_id}/generate")
def generate_exam(
    document_id: int,
    request: Request,
    exam_title: str = Form(...),
    quantity: int = Form(5),
    difficulty: str = Form("Trung bình"),
    category: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")

    try:
        questions = generate_questions(
            document.extracted_text or "",
            quantity=quantity,
            difficulty=difficulty,
        )
    except AIServiceError as exc:
        exams = (
            db.query(Exam)
            .filter(Exam.document_id == document.id, Exam.user_id == user.id)
            .order_by(Exam.created_at.desc())
            .all()
        )
        return templates.TemplateResponse(
            "document_detail.html",
            {
                "request": request,
                "user": user,
                "document": document,
                "preview_text": (document.extracted_text or "")[:3000],
                "exams": exams,
                "error": str(exc),
            },
            status_code=400,
        )

    exam = Exam(
        user_id=user.id,
        document_id=document.id,
        title=exam_title.strip() or f"Đề thi từ {document.title}",
        difficulty=difficulty,
        category=category.strip() or None,
    )
    db.add(exam)
    db.flush()

    for item in questions:
        q = Question(
            exam_id=exam.id,
            content=item["content"],
            option_a=item["option_a"],
            option_b=item["option_b"],
            option_c=item["option_c"],
            option_d=item["option_d"],
            correct_answer=item["correct_answer"],
            explanation=item.get("explanation", ""),
        )
        db.add(q)

    db.commit()
    db.refresh(exam)
    log_action(db, user.id, f"Tạo đề thi: {exam.title} ({len(questions)} câu)")
    return RedirectResponse(url=f"/exams/{exam.id}", status_code=303)


@app.get("/exams", response_class=HTMLResponse)
def exams_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    exams = db.query(Exam).filter(Exam.user_id == user.id).order_by(Exam.created_at.desc()).all()
    return templates.TemplateResponse("exams.html", {"request": request, "user": user, "exams": exams})


@app.get("/exams/{exam_id}", response_class=HTMLResponse)
def exam_detail(exam_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user.id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi.")
    return templates.TemplateResponse("exam_detail.html", {"request": request, "user": user, "exam": exam})


@app.get("/questions/{question_id}/edit", response_class=HTMLResponse)
def edit_question_page(question_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = db.query(Question).join(Exam).filter(Question.id == question_id, Exam.user_id == user.id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Không tìm thấy câu hỏi.")
    return templates.TemplateResponse("edit_question.html", {"request": request, "user": user, "question": question})


@app.post("/questions/{question_id}/edit")
def edit_question(
    question_id: int,
    content: str = Form(...),
    option_a: str = Form(...),
    option_b: str = Form(...),
    option_c: str = Form(...),
    option_d: str = Form(...),
    correct_answer: str = Form(...),
    explanation: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    question = db.query(Question).join(Exam).filter(Question.id == question_id, Exam.user_id == user.id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Không tìm thấy câu hỏi.")

    question.content = content.strip()
    question.option_a = option_a.strip()
    question.option_b = option_b.strip()
    question.option_c = option_c.strip()
    question.option_d = option_d.strip()
    question.correct_answer = correct_answer.strip().upper()[:1]
    question.explanation = explanation.strip()
    db.commit()
    log_action(db, user.id, f"Sửa câu hỏi #{question.id}")
    return RedirectResponse(url=f"/exams/{question.exam_id}", status_code=303)


@app.post("/questions/{question_id}/delete")
def delete_question(question_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = db.query(Question).join(Exam).filter(Question.id == question_id, Exam.user_id == user.id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Không tìm thấy câu hỏi.")
    exam_id = question.exam_id
    db.delete(question)
    db.commit()
    log_action(db, user.id, f"Xóa câu hỏi #{question_id}")
    return RedirectResponse(url=f"/exams/{exam_id}", status_code=303)


@app.get("/exams/{exam_id}/export/{file_type}")
def export_exam(exam_id: int, file_type: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user.id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi.")

    if file_type == "docx":
        path = export_exam_docx(exam, EXPORT_DIR)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file_type == "pdf":
        path = export_exam_pdf(exam, EXPORT_DIR)
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="Định dạng không hợp lệ.")

    log_action(db, user.id, f"Xuất đề thi: {exam.title} ({file_type})")
    return FileResponse(path, media_type=media_type, filename=Path(path).name)


@app.post("/exams/{exam_id}/delete")
def delete_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user.id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi.")
    title = exam.title
    db.delete(exam)
    db.commit()
    log_action(db, user.id, f"Xóa đề thi: {title}")
    return RedirectResponse(url="/exams", status_code=303)
