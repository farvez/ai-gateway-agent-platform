from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Team(Base):
    """A group of users (e.g. "search", "support") with its own keys, budget and limits."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # None means "no limit".
    monthly_budget_usd: Mapped[float | None] = mapped_column(Float)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApiKey(Base):
    """A key a team uses to call the gateway.

    Only a SHA-256 hash of the key is stored, never the key itself, so a leaked
    database doesn't leak usable keys. The key is shown once, when it's created.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(100))  # e.g. "prod backend"
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # The first few characters, so people can tell keys apart without seeing them.
    key_prefix: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestLog(Base):
    """One row per /chat or /chat/stream request.

    The message text is deliberately not stored: prompts can contain private data,
    and the numbers below are all that usage and cost reporting needs.
    """

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)

    endpoint: Mapped[str] = mapped_column(String(20))  # "chat" or "stream"
    # "success", "error" (every provider failed), "stream_error" (failed mid-stream)
    # or "cancelled" (client disconnected mid-stream)
    status: Mapped[str] = mapped_column(String(20), index=True)

    requested_provider: Mapped[str] = mapped_column(String(50))
    served_by: Mapped[str | None] = mapped_column(String(50), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    fallback_used: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)  # None if the price is unknown

    latency_ms: Mapped[int] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)  # streaming only

    error: Mapped[str | None] = mapped_column(Text)
