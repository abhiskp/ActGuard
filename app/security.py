from __future__ import annotations

import os
from secrets import compare_digest

from fastapi import Header, HTTPException, status

ADMIN_TOKEN_ENV = "ACTGUARD_ADMIN_TOKEN"
ADMIN_TOKEN_HEADER = "X-ActGuard-Admin-Token"


def require_admin_token(
    admin_token: str | None = Header(default=None, alias=ADMIN_TOKEN_HEADER),
) -> None:
    expected_token = os.getenv(ADMIN_TOKEN_ENV, "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{ADMIN_TOKEN_ENV} is not configured.",
        )

    submitted_token = admin_token.strip() if admin_token else ""
    if not submitted_token or not compare_digest(submitted_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid ActGuard admin token required.",
        )
