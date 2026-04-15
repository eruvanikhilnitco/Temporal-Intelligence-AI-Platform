from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.schemas.auth import UserSignUp, UserLogin, TokenResponse, TokenRefresh, UserResponse
from app.services.auth_service import AuthService
from app.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=dict)
async def signup(user_data: UserSignUp, db: Session = Depends(get_db)):
    """Register a new user (legacy — defaults to client role)"""
    try:
        user_data.role = "client"
        user = AuthService.register_user(db, user_data)
        return {"status": "success", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/signup/user", response_model=dict)
async def signup_user(user_data: UserSignUp, db: Session = Depends(get_db)):
    """Register a standard user account (chat-only access)"""
    try:
        user_data.role = "client"
        user = AuthService.register_user(db, user_data)
        return {"status": "success", "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/signup/admin", response_model=dict)
async def signup_admin(user_data: UserSignUp, db: Session = Depends(get_db)):
    """Admin signup is disabled — the superadmin account is provisioned at server startup."""
    raise HTTPException(
        status_code=403,
        detail=(
            "Admin self-registration is disabled. "
            "The superadmin account is pre-provisioned by the system. "
            "Contact your system administrator for access."
        ),
    )


@router.post("/login", response_model=dict)
async def login(login_data: UserLogin, db: Session = Depends(get_db)):
    """Login any user (non-admin path) and get tokens. Admin users are redirected to /auth/login/admin."""
    try:
        result = AuthService.login_user(db, login_data)
        # Block admins from using the standard login endpoint
        if result["user"].role == "admin":
            raise HTTPException(
                status_code=403,
                detail="Admin accounts must use the admin login portal.",
            )
        return {
            "status": "success",
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "user": result["user"],
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/login/admin", response_model=dict)
async def login_admin(login_data: UserLogin, db: Session = Depends(get_db)):
    """Admin-only login portal. Validates org email domain and admin role."""
    from app.services.auth_service import ADMIN_EMAIL_DOMAIN
    # Enforce org domain at login time too
    domain = login_data.email.split("@")[-1].lower() if "@" in login_data.email else ""
    if domain != ADMIN_EMAIL_DOMAIN:
        raise HTTPException(
            status_code=403,
            detail=f"Admin login requires an organisation email (@{ADMIN_EMAIL_DOMAIN}).",
        )
    try:
        result = AuthService.login_user(db, login_data)
        if result["user"].role != "admin":
            raise HTTPException(status_code=403, detail="This account does not have admin privileges.")
        return {
            "status": "success",
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "user": result["user"],
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/refresh", response_model=dict)
async def refresh(token_data: TokenRefresh):
    """Refresh access token"""
    try:
        new_token = AuthService.refresh_access_token(token_data.refresh_token)
        return {"status": "success", "access_token": new_token}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user info"""
    try:
        user = AuthService.get_user_by_id(db, current_user["user_id"])
        return user
    except ValueError:
        raise HTTPException(status_code=404, detail="User not found")


@router.get("/users", response_model=list)
async def list_users(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users (admin only)"""
    users = AuthService.get_all_users(db)
    return users


@router.post("/users/{user_id}/block", response_model=UserResponse)
async def block_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Block a user"""
    try:
        user = AuthService.block_user(db, user_id)
        return user
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/users/{user_id}/unblock", response_model=UserResponse)
async def unblock_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unblock a user"""
    try:
        user = AuthService.unblock_user(db, user_id)
        return user
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    new_role: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update user role"""
    try:
        user = AuthService.update_user_role(db, user_id, new_role)
        return user
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
