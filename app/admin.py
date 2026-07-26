from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .database import get_db
from .models import User, Document, Exam
from .security import get_current_user
from .models import ActivityLog

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin", tags=["Admin"])


def log_activity(db: Session, user_id: int, action: str):
    log = ActivityLog(user_id=user_id, action=action)
    db.add(log)
    db.commit()


def check_admin(user: User):
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Bạn không có quyền Admin"
        )


@router.get("/activity_logs")
def get_activity_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_admin(current_user)

    logs = db.query(ActivityLog).order_by(ActivityLog.timestamp.desc()).all()
    return [
        {
            "id": log.id,
            "user": log.user.full_name if log.user else "Unknown",
            "action": log.action,
            "timestamp": log.timestamp
        }
        for log in logs
    ]


@router.get("")
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_admin(current_user)

    total_users = db.query(User).count()
    total_documents = db.query(Document).count()
    total_exams = db.query(Exam).count()

    return {
        "total_users": total_users,
        "total_documents": total_documents,
        "total_exams": total_exams
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_admin(current_user)
    users = db.query(User).all()
    return users


@router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Đổi quyền của user giữa 'admin' và 'user'."""
    check_admin(current_user)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Không thể tự đổi quyền của chính mình.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user")

    user.role = "user" if user.role == "admin" else "admin"
    db.commit()
    log_activity(db, current_user.id, f"Đổi quyền user #{user_id} thành '{user.role}'")

    return {"message": "Đã cập nhật quyền", "role": user.role}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    check_admin(current_user)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Không thể tự xóa chính mình.")

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user")

    deleted_email = user.email
    db.delete(user)
    db.commit()

    log_activity(db, current_user.id, f"Xóa người dùng #{user_id} ({deleted_email})")

    return {"message": "Đã xóa người dùng"}


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)
    return templates.TemplateResponse("admin.html", {"request": request, "user": current_user})


@router.get("/activity")
def get_activity_log(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    check_admin(current_user)
    logs = db.query(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(50).all()
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "timestamp": log.timestamp,
        }
        for log in logs
    ]
