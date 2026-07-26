from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from .database import get_db
from .models import User, Document, Exam
from .security import get_current_user
from .models import ActivityLog

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(prefix="/admin", tags=["Admin"])


# kiểm tra quyền admin
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
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Bạn không có quyền Admin")
    
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

@router.delete("/users/{user_id}")
def delete_user(

    user_id:int,

    db:Session=Depends(get_db),

    current_user:User=Depends(get_current_user)

):

    check_admin(current_user)


    user=db.query(User).filter(
        User.id==user_id
    ).first()


    if not user:

        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy user"
        )


    db.delete(user)

    db.commit()


    return {
        "message":"Đã xóa người dùng"
    }

@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@router.get("/activity")
def get_activity_log(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    check_admin(current_user)
    logs = db.query(ActivityLog).order_by(ActivityLog.timestamp.desc()).limit(50).all()
    return logs