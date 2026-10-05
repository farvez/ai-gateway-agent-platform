import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select

from app.db import SessionLocal
from app.models import RequestLog, Team

logger = logging.getLogger(__name__)


def record_request(**fields) -> None:
    """Save one request to the database.

    Never raises: if the database is unavailable the user should still get their
    answer, so a failure here is logged as a warning instead.
    """
    try:
        with SessionLocal() as session:
            session.add(RequestLog(**fields))
            session.commit()
    except Exception:
        logger.warning("Could not record request usage", exc_info=True)


def team_spend_since(team_id: int, since: datetime) -> float:
    """Total USD a team has spent since a point in time (used for budget checks)."""
    with SessionLocal() as session:
        return session.scalar(
            select(func.coalesce(func.sum(RequestLog.cost_usd), 0.0)).where(
                RequestLog.team_id == team_id, RequestLog.created_at >= since
            )
        )


def summarize(
    hours: float | None = None, team_id: int | None = None, since: datetime | None = None
) -> dict:
    """Totals, latency percentiles and per-provider / per-model / per-team breakdowns.

    Pass team_id to only count one team's requests (what a team sees at /me).
    """

    if since is None and hours:
        since = datetime.now(UTC) - timedelta(hours=hours)

    filters = []
    if since is not None:
        filters.append(RequestLog.created_at >= since)
    if team_id is not None:
        filters.append(RequestLog.team_id == team_id)

    with SessionLocal() as session:
        totals = session.execute(_aggregate_query(filters)).one()

        # Group by who actually answered; failed requests have no served_by,
        # so they are counted under the provider that was requested.
        provider = func.coalesce(RequestLog.served_by, RequestLog.requested_provider)
        by_provider = session.execute(
            _aggregate_query(filters, provider.label("provider")).group_by(provider)
        ).all()
        by_model = session.execute(
            _aggregate_query(filters, RequestLog.model)
            .where(RequestLog.model.is_not(None))
            .group_by(RequestLog.model)
        ).all()

        by_team = session.execute(
            _aggregate_query(filters, RequestLog.team_id, Team.name.label("team"))
            .outerjoin(Team, RequestLog.team_id == Team.id)
            .group_by(RequestLog.team_id, Team.name)
        ).all()

        latencies = _column_values(session, RequestLog.latency_ms, filters)
        ttfts = _column_values(session, RequestLog.ttft_ms, filters)

    return {
        "window_hours": hours,
        "totals": {
            **_row_to_stats(totals),
            "latency_ms": _percentiles(latencies),
            "ttft_ms": _percentiles(ttfts),
        },
        "by_provider": [{"provider": r.provider, **_row_to_stats(r)} for r in by_provider],
        "by_model": [{"model": r.model, **_row_to_stats(r)} for r in by_model],
        # Requests made before teams existed have no team.
        "by_team": [{"team_id": r.team_id, "team": r.team, **_row_to_stats(r)} for r in by_team],
    }


def recent(limit: int = 20, team_id: int | None = None) -> list[dict]:
    """The latest requests, newest first."""
    query = select(RequestLog).order_by(RequestLog.id.desc()).limit(limit)
    if team_id is not None:
        query = query.where(RequestLog.team_id == team_id)

    with SessionLocal() as session:
        rows = session.scalars(query).all()
        return [
            {column.name: getattr(row, column.name) for column in RequestLog.__table__.columns}
            for row in rows
        ]


def _aggregate_query(filters: list, *group_columns):
    is_failure = case((RequestLog.status != "success", 1), else_=0)
    query = select(
        *group_columns,
        func.count(RequestLog.id).label("requests"),
        func.coalesce(func.sum(is_failure), 0).label("failures"),
        func.coalesce(func.sum(case((RequestLog.fallback_used, 1), else_=0)), 0).label("fallbacks"),
        func.coalesce(func.sum(RequestLog.input_tokens), 0).label("input_tokens"),
        func.coalesce(func.sum(RequestLog.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(RequestLog.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(RequestLog.cost_usd), 0.0).label("cost_usd"),
        func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
    )
    return query.where(*filters)


def _row_to_stats(row) -> dict:
    return {
        "requests": row.requests,
        "failures": row.failures,
        "success_rate": round(1 - row.failures / row.requests, 4) if row.requests else None,
        "fallbacks": row.fallbacks,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "cost_usd": round(row.cost_usd, 8),
        "avg_latency_ms": round(row.avg_latency_ms) if row.avg_latency_ms is not None else None,
    }


def _column_values(session, column, filters: list) -> list[int]:
    # Percentiles only make sense for requests that succeeded.
    query = select(column).where(RequestLog.status == "success", column.is_not(None), *filters)
    return sorted(session.scalars(query).all())


def _percentiles(values: list[int]) -> dict:
    if not values:
        return {"p50": None, "p95": None}
    return {"p50": _percentile(values, 50), "p95": _percentile(values, 95)}


def _percentile(sorted_values: list[int], pct: float) -> int:
    # Nearest-rank method: the smallest value with at least pct% of values at or below it.
    rank = max(1, -(-len(sorted_values) * pct // 100))  # ceil without importing math
    return sorted_values[int(rank) - 1]
