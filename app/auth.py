from functools import wraps
from fastapi import Request, HTTPException

def optional_auth(func):
    """Placeholder decorator for future authentication.
    Currently it just passes through the request.
    When real auth is needed replace the body with actual checks.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # In future: validate token, raise HTTPException(401) if invalid
        return await func(*args, **kwargs)
    return wrapper
