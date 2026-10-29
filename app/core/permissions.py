from fastapi import Depends, HTTPException, status
from app.core.deps import get_current_user

def require_roles(*roles: str):
    """
    Factory trả về dependency kiểm tra role.
    Dùng: Depends(require_roles("admin", "user"))
    """
    allowed_roles = {role.casefold() for role in roles}
    if not allowed_roles:
        raise ValueError("require_roles needs at least one role")

    def checker(current_user = Depends(get_current_user)):
        role_code = current_user.role.code.casefold() if current_user.role else ""
        if role_code not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện thao tác này"
            )
        return current_user
    return checker
