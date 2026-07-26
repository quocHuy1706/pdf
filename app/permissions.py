from fastapi import HTTPException


def require_admin(user):

    if user.role != "admin":

        raise HTTPException(
            status_code=403,
            detail="Bạn không có quyền Admin"
        )