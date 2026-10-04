from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RequestLog(Base):
    """One row per /chat or /chat/stream request.

    The message text is deliberately not stored: prompts can contain private data,
    and the numbers below are all that usage and cost reporting needs.
    """

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

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
