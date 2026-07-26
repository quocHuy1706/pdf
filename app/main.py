from fastapi import APIRouter,FastAPI, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from pathlib import Path
import os
import shutil
from . import admin
from .models import ActivityLog
from dotenv import load_dotenv
from .security import get_current_user
from .database import Base, engine, get_db
from .models import User, Document, Exam, Question
from .security import hash_password, verify_password
from .pdf_utils import extract_text_from_pdf
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
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.include_router(admin.router)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)

def check_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Bạn không có quyền Admin")

@router.get("/activity-log")
def get_activity_log(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_admin(current_user)
    logs = db.query(ActivityLog).order_by(ActivityLog.timestamp.desc()).all()
    return [
        {"id": log.id, "user_id": log.user_id, "action": log.action, "timestamp": log.timestamp}
        for log in logs
    ]

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
    return RedirectResponse(url="/login", status_code=303)


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
    exists = db.query(User).filter(User.email == email.strip().lower()).first()
    if exists:
        return templates.TemplateResponse("register.html", {"request": request, "user": None, "error": "Email đã tồn tại."})

    user = User(full_name=full_name.strip(), email=email.strip().lower(), password_hash=hash_password(password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return templates.TemplateResponse("login.html", {"request": request, "user": user, "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "user": None, "error": "Email hoặc mật khẩu không đúng."})
    request.session["user_id"] = user.id
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    documents = db.query(Document).filter(Document.user_id == user.id).order_by(Document.created_at.desc()).all()
    exams = db.query(Exam).filter(Exam.user_id == user.id).order_by(Exam.created_at.desc()).limit(5).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user, "documents": documents, "exams": exams})


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": None})


@app.post("/upload")
def upload_pdf(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not file.filename.lower().endswith(".pdf"):
        return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": "Vui lòng chọn file PDF."})

    safe_filename = f"user_{user.id}_{file.filename.replace(' ', '_')}"
    file_path = Path(UPLOAD_DIR) / safe_filename
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        extracted_text = extract_text_from_pdf(str(file_path))
    except Exception as exc:
        return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": f"Không đọc được PDF: {exc}"})

    document = Document(user_id=user.id, title=title.strip() or file.filename, file_path=str(file_path), extracted_text=extracted_text)
    db.add(document)
    db.commit()
    db.refresh(document)
    return RedirectResponse(url=f"/documents/{document.id}", status_code=303)


@app.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(document_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == user.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài liệu.")
    exams = db.query(Exam).filter(Exam.document_id == document.id, Exam.user_id == user.id).order_by(Exam.created_at.desc()).all()
    preview_text = (document.extracted_text or "")[:3000]
    return templates.TemplateResponse("document_detail.html", {"request": request, "user": user, "document": document, "preview_text": preview_text, "exams": exams})


@app.post("/documents/{document_id}/generate")
def generate_exam(
    document_id: int,
    request: Request,
    exam_title: str = Form(...),
    quantity: int = Form(5),
    difficulty: str = Form("Trung bình"),
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

    exam = Exam(user_id=user.id, document_id=document.id, title=exam_title.strip() or f"Đề thi từ {document.title}", difficulty=difficulty)
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
    return RedirectResponse(url=f"/exams/{question.exam_id}", status_code=303)


@app.post("/questions/{question_id}/delete")
def delete_question(question_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = db.query(Question).join(Exam).filter(Question.id == question_id, Exam.user_id == user.id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Không tìm thấy câu hỏi.")
    exam_id = question.exam_id
    db.delete(question)
    db.commit()
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

    return FileResponse(path, media_type=media_type, filename=Path(path).name)


@app.post("/exams/{exam_id}/delete")
def delete_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    exam = db.query(Exam).filter(Exam.id == exam_id, Exam.user_id == user.id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi.")
    db.delete(exam)
    db.commit()
    return RedirectResponse(url="/exams", status_code=303)

