from fastapi import Depends

from core.security import verify_api_key


def require_api_key():
    return Depends(verify_api_key)
