import hashlib
import hmac
import os
from itsdangerous import URLSafeSerializer, BadSignature
from dotenv import load_dotenv

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
load_dotenv()

SECRET_KEY = os.getenv("APP_SECRET_KEY", "change-this-secret-key")
serializer = URLSafeSerializer(SECRET_KEY, salt="exam-ai-session")

# Chống brute-force cực kỳ đơn giản (trong bộ nhớ tiến trình).
# Với hệ thống nhiều tiến trình/nhiều máy nên thay bằng Redis.
_LOGIN_ATTEMPTS: dict[str, int] = {}
MAX_LOGIN_ATTEMPTS = 10


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"{salt}${hashed}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, hashed = password_hash.split("$")
        new_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
        return hmac.compare_digest(new_hash, hashed)
    except Exception:
        return False


def register_failed_login(email: str) -> None:
    _LOGIN_ATTEMPTS[email] = _LOGIN_ATTEMPTS.get(email, 0) + 1


def reset_failed_login(email: str) -> None:
    _LOGIN_ATTEMPTS.pop(email, None)


def is_login_locked(email: str) -> bool:
    return _LOGIN_ATTEMPTS.get(email, 0) >= MAX_LOGIN_ATTEMPTS


def update_password(db: Session, user: User, new_password: str) -> None:
    """Đổi mật khẩu cho user (dùng cho tự đổi mật khẩu hoặc admin reset hộ)."""
    user.password_hash = hash_password(new_password)
    db.add(user)
    db.commit()


def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})


def read_session_token(token: str):
    try:
        data = serializer.loads(token)
        return data.get("user_id")
    except BadSignature:
        return None

def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):

    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Chưa đăng nhập"
        )

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy người dùng"
        )

    return user
