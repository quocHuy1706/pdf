from fastapi import HTTPException


def require_admin(user) -> None:
    """Chặn nếu user không phải admin. Đây là nơi DUY NHẤT chứa logic
    kiểm tra quyền admin trong toàn bộ app — mọi chỗ khác nên gọi lại
    hàm này thay vì viết lại điều kiện role == 'admin'."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Bạn không có quyền Admin")