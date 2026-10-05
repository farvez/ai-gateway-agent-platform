import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, Team

KEY_PREFIX = "gw-"

# Two separate schemes so Swagger UI (/docs) shows one "Authorize" box for a team key
# and one for the admin key. auto_error=False lets us return our own 401 message.
team_bearer = HTTPBearer(scheme_name="TeamKey", auto_error=False)
admin_bearer = HTTPBearer(scheme_name="AdminKey", auto_error=False)


@dataclass(frozen=True)
class TeamContext:
    """Who is making the request, loaded from their API key."""

    team_id: int
    team_name: str
    key_id: int
    monthly_budget_usd: float | None
    rate_limit_per_minute: int | None


def hash_key(key: str) -> str:
    # A fast hash is fine here, unlike for passwords: keys are 32 random bytes, so
    # there is nothing to guess and no need for a slow hash like bcrypt.
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def issue_key(team_id: int, name: str | None = None) -> tuple[ApiKey, str]:
    """Create a key for a team. Returns the stored row and the plain key, which is
    never stored and can't be shown again."""
    plain = generate_key()
    with SessionLocal() as session:
        row = ApiKey(team_id=team_id, name=name, key_hash=hash_key(plain), key_prefix=plain[:10])
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
    return row, plain


def lookup_key(plain: str) -> TeamContext | None:
    """Find the team for a key, or None if the key is unknown or revoked."""
    with SessionLocal() as session:
        row = session.execute(
            select(ApiKey, Team)
            .join(Team, ApiKey.team_id == Team.id)
            .where(ApiKey.key_hash == hash_key(plain), ApiKey.revoked_at.is_(None))
        ).first()

    if row is None:
        return None

    key, team = row
    return TeamContext(
        team_id=team.id,
        team_name=team.name,
        key_id=key.id,
        monthly_budget_usd=team.monthly_budget_usd,
        rate_limit_per_minute=team.rate_limit_per_minute,
    )


def revoke_key(key_id: int) -> bool:
    with SessionLocal() as session:
        key = session.get(ApiKey, key_id)
        if key is None:
            return False
        if key.revoked_at is None:
            key.revoked_at = datetime.now(UTC)
            session.commit()
    return True


# ---------- FastAPI dependencies ----------


def require_team(
    credentials: HTTPAuthorizationCredentials | None = Depends(team_bearer),
) -> TeamContext:
    """Rejects the request with 401 unless it carries a valid, unrevoked team key."""

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Send it as: Authorization: Bearer gw-...",
            headers={"WWW-Authenticate": "Bearer"},
        )

    team = lookup_key(credentials.credentials)
    if team is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return team


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(admin_bearer),
) -> None:
    """Rejects the request unless it carries the ADMIN_API_KEY from the environment."""

    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key:
        raise HTTPException(
            status_code=503, detail="Admin API is disabled: set ADMIN_API_KEY in .env."
        )

    # compare_digest takes the same time whether the first character or the last one
    # differs, so an attacker can't guess the key one character at a time by timing.
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), admin_key.encode()
    ):
        raise HTTPException(
            status_code=401, detail="Invalid admin key.", headers={"WWW-Authenticate": "Bearer"}
        )
