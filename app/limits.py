import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException

from app import usage
from app.auth import TeamContext, require_team


class RateLimiter:
    """Sliding-window limiter: at most `limit` requests in any `window` seconds.

    It keeps the timestamps of recent requests per team in memory. That's enough for
    one server process; with several processes or servers the counts must live in a
    shared store such as Redis, otherwise each process allows the full limit.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # endpoints run in a thread pool

    def check(self, team_id: int, limit: int, window: float = 60.0) -> float | None:
        """Record a request. Returns None if allowed, or seconds to wait if not."""
        now = self._clock()
        with self._lock:
            hits = self._hits[team_id]
            while hits and hits[0] <= now - window:
                hits.popleft()

            if len(hits) >= limit:
                return window - (now - hits[0])

            hits.append(now)
            return None


limiter = RateLimiter()


def start_of_month() -> datetime:
    return datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def budget_status(team: TeamContext) -> dict:
    spent = usage.team_spend_since(team.team_id, start_of_month())
    budget = team.monthly_budget_usd

    return {
        "monthly_budget_usd": budget,
        "spent_this_month_usd": round(spent, 8),
        "remaining_usd": round(max(budget - spent, 0), 8) if budget is not None else None,
        "used_pct": round(spent / budget * 100, 1) if budget else None,
    }


def require_team_within_limits(team: TeamContext = Depends(require_team)) -> TeamContext:
    """Authenticate, then check the rate limit, then the budget, before any provider
    is called. Cheapest checks first; a rejected request costs nothing."""

    if team.rate_limit_per_minute is not None:
        retry_after = limiter.check(team.team_id, team.rate_limit_per_minute)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit of {team.rate_limit_per_minute} requests/minute reached.",
                headers={"Retry-After": str(math.ceil(retry_after))},
            )

    if team.monthly_budget_usd is not None:
        status = budget_status(team)
        if status["remaining_usd"] == 0:
            # 402 rather than 429: clients retry 429s automatically, but waiting
            # a few seconds won't help a team that has spent its monthly budget.
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Monthly budget of ${team.monthly_budget_usd:.2f} reached "
                    f"(${status['spent_this_month_usd']:.4f} spent). Ask an admin to raise it."
                ),
            )

    return team
