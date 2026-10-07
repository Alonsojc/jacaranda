"""
Rate limiting middleware para FastAPI.
Limita peticiones por IP sin dependencias externas.
"""

import time
from collections import defaultdict
from threading import Lock
from fastapi import Request, Response
from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# {ip: [timestamp1, timestamp2, ...]}
_requests: dict[str, list[float]] = defaultdict(list)
_authorization_lock = Lock()

# Config
RATE_LIMIT = 900  # requests per window; dashboard opens several reads per device
RATE_WINDOW = 60  # seconds

# Stricter limit for auth endpoints
AUTH_RATE_LIMIT = 10
AUTH_RATE_WINDOW = 60
AUTH_SESSION_RATE_LIMIT = 300

# Exempt paths (health checks, static, docs)
EXEMPT_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _cleanup_old(entries: list[float], window: float) -> list[float]:
    cutoff = time.time() - window
    return [t for t in entries if t > cutoff]


def check_authorization_rate_limit(user_id: int) -> None:
    """Limit credential checks across all sensitive actions for this user."""
    key = f"authorization:{user_id}"
    with _authorization_lock:
        _requests[key] = _cleanup_old(_requests[key], AUTH_RATE_WINDOW)
        if len(_requests[key]) >= AUTH_RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Demasiados intentos de autorizacion. Espera un minuto.",
                headers={"Retry-After": str(AUTH_RATE_WINDOW)},
            )
        _requests[key].append(time.time())


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Exempt paths
        if path in EXEMPT_PATHS:
            return await call_next(request)

        ip = _get_client_ip(request)

        # Determine limits based on path
        if path.endswith("/auth/login"):
            max_requests = AUTH_RATE_LIMIT
            window = AUTH_RATE_WINDOW
            key = f"auth:{ip}"
        elif path.endswith("/auth/me") or path.endswith("/auth/refresh"):
            max_requests = AUTH_SESSION_RATE_LIMIT
            window = AUTH_RATE_WINDOW
            key = f"auth-session:{ip}"
        else:
            max_requests = RATE_LIMIT
            window = RATE_WINDOW
            key = f"api:{ip}"

        # Cleanup and check
        _requests[key] = _cleanup_old(_requests[key], window)

        if len(_requests[key]) >= max_requests:
            return Response(
                content='{"detail":"Demasiadas peticiones. Intente más tarde."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                },
            )

        _requests[key].append(time.time())
        remaining = max_requests - len(_requests[key])

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(remaining, 0))
        return response
