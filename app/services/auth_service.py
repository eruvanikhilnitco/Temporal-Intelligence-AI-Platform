import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import UserSignUp, UserLogin, UserResponse

logger = logging.getLogger(__name__)

# Organisation email domain — only this domain may register/login as admin
ADMIN_EMAIL_DOMAIN = "nitcoinc.com"


class AuthService:
    @staticmethod
    def _enforce_admin_email(email: str):
        """Raise ValueError if the email is not from the org domain."""
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain != ADMIN_EMAIL_DOMAIN:
            raise ValueError(
                f"Admin accounts require an organisation email (@{ADMIN_EMAIL_DOMAIN})."
            )

    @staticmethod
    def register_user(db: Session, user_data: UserSignUp) -> UserResponse:
        """Register a new user"""
        try:
            # Admin accounts must use the org email domain
            if getattr(user_data, "role", None) == "admin":
                AuthService._enforce_admin_email(user_data.email)

            # Check if user exists
            existing = db.query(User).filter(User.email == user_data.email).first()
            if existing:
                raise ValueError("Email already registered")

            # Create new user
            db_user = User(
                email=user_data.email,
                name=user_data.name,
                password_hash=hash_password(user_data.password),
                role=user_data.role or "client",
            )
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            logger.info(f"User registered: {user_data.email}")
            return UserResponse.from_orm(db_user)
        except IntegrityError:
            db.rollback()
            raise ValueError("Email already registered")
        except Exception as e:
            db.rollback()
            logger.error(f"Registration error: {e}")
            raise

    @staticmethod
    def login_user(db: Session, login_data: UserLogin) -> dict:
        """Authenticate user and return tokens"""
        user = db.query(User).filter(User.email == login_data.email).first()

        if not user or not verify_password(login_data.password, user.password_hash):
            if user:
                user.login_attempts += 1
                db.commit()
            raise ValueError("Invalid email or password")

        if not user.is_active:
            raise ValueError("User account is inactive")

        # Reset login attempts
        user.login_attempts = 0
        from datetime import datetime
        user.last_login = datetime.utcnow()
        db.commit()

        # Generate tokens
        access_token = create_access_token({"sub": user.id, "email": user.email, "role": user.role})
        refresh_token = create_refresh_token({"sub": user.id})

        logger.info(f"User logged in: {user.email}")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": UserResponse.from_orm(user),
        }

    @staticmethod
    def refresh_access_token(refresh_token: str) -> str:
        """Generate new access token from refresh token"""
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")

        user_id = payload.get("sub")
        new_access_token = create_access_token({"sub": user_id})
        return new_access_token

    @staticmethod
    def get_user_by_id(db: Session, user_id: str) -> UserResponse:
        """Get user by ID"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        return UserResponse.from_orm(user)

    @staticmethod
    def get_all_users(db: Session) -> list:
        """Get all users (admin only)"""
        users = db.query(User).all()
        return [UserResponse.from_orm(u) for u in users]

    @staticmethod
    def block_user(db: Session, user_id: str) -> UserResponse:
        """Block/deactivate user"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        user.is_active = False
        db.commit()
        db.refresh(user)
        logger.info(f"User blocked: {user.email}")
        return UserResponse.from_orm(user)

    @staticmethod
    def unblock_user(db: Session, user_id: str) -> UserResponse:
        """Unblock/reactivate user"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        user.is_active = True
        db.commit()
        db.refresh(user)
        logger.info(f"User unblocked: {user.email}")
        return UserResponse.from_orm(user)

    @staticmethod
    def update_user_role(db: Session, user_id: str, new_role: str) -> UserResponse:
        """Update user role"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        user.role = new_role
        db.commit()
        db.refresh(user)
        logger.info(f"User role updated: {user.email} → {new_role}")
        return UserResponse.from_orm(user)
