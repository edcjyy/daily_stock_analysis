# -*- coding: utf-8 -*-
"""
Auth middleware: protect /api/v1/* when admin auth is enabled.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import COOKIE_NAME, is_auth_enabled, verify_session

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/v1/health",
    "/api/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})


def _path_exempt(path: str) -> bool:
    """Check if path is exempt from auth."""
    normalized = path.rstrip("/") or "/"
    return normalized in EXEMPT_PATHS


_api_token: str | None = None


def get_api_token() -> str | None:
    """Lazily read API_TOKEN from environment, cache the result."""
    global _api_token
    if _api_token is None:
        _api_token = os.environ.get("API_TOKEN", "") or None
    return _api_token


def verify_api_token(token: str) -> bool:
    """Verify a Bearer token using constant-time comparison."""
    expected = get_api_token()
    if not expected:
        return False
    return hmac.compare_digest(token, expected)


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid session for /api/v1/* when auth is enabled."""

    _logged_api_token: bool = False

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        # Log API token status once on first request
        if not AuthMiddleware._logged_api_token:
            AuthMiddleware._logged_api_token = True
            logger.info("API Token authentication: %s", "enabled" if get_api_token() else "disabled")

        if not is_auth_enabled():
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path):
            return await call_next(request)

        if not path.startswith("/api/v1/"):
            return await call_next(request)

        # Check API Token first (Bearer token in Authorization header)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_api_token(token):
                return await call_next(request)
            # Invalid token - return 401
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "message": "Invalid API token"},
            )

        cookie_val = request.cookies.get(COOKIE_NAME)
        if not cookie_val or not verify_session(cookie_val):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Login required",
                },
            )

        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API routes.

    The middleware is always registered; whether auth is enforced is determined
    at request time by is_auth_enabled() so the decision stays consistent across
    any runtime configuration reload.
    """
    app.add_middleware(AuthMiddleware)
