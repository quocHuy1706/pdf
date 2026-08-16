import hashlib
import hmac
import os
from dotenv import load_dotenv

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .permissions import require_admin

load_dotenv()

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


# ---------------------------------------------------------------------------
# Dependency dùng chung cho TOÀN BỘ app (main.py và admin.py đều import từ đây,
# không tự viết lại logic đọc session nữa).
# ---------------------------------------------------------------------------

def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Trả về user hiện tại nếu đã đăng nhập, ngược lại trả None (KHÔNG raise lỗi).
    Dùng cho các trang công khai cần biết trạng thái đăng nhập, ví dụ trang chủ,
    trang login/register (để tự động redirect nếu đã đăng nhập)."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Yêu cầu đăng nhập: trả về user hoặc raise 401 nếu chưa đăng nhập."""
    user = get_optional_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Yêu cầu đăng nhập VÀ có quyền admin. Raise 401 nếu chưa đăng nhập,
    403 nếu không phải admin. Dùng cho mọi route trong admin.py."""
    require_admin(user)
    return user