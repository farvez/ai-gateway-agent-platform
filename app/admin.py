from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import auth
from app.auth import TeamContext, require_admin
from app.db import SessionLocal
from app.limits import budget_status
from app.models import ApiKey, Team

# Every route here needs the admin key.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["search"])
    monthly_budget_usd: float | None = Field(default=None, ge=0, examples=[50.0])
    rate_limit_per_minute: int | None = Field(default=None, ge=1, examples=[60])


class TeamUpdate(BaseModel):
    # Only the fields you send are changed; send null to remove a limit.
    monthly_budget_usd: float | None = Field(default=None, ge=0)
    rate_limit_per_minute: int | None = Field(default=None, ge=1)


class KeyCreate(BaseModel):
    name: str | None = Field(default=None, max_length=100, examples=["prod backend"])


@router.post("/teams", status_code=201)
def create_team(body: TeamCreate):
    with SessionLocal() as session:
        team = Team(**body.model_dump())
        session.add(team)
        try:
            session.commit()
        except IntegrityError as e:
            raise HTTPException(
                status_code=409, detail=f"Team '{body.name}' already exists."
            ) from e
        return _team_out(team)


@router.get("/teams")
def list_teams():
    """All teams with their budget and this month's spend."""
    with SessionLocal() as session:
        teams = session.scalars(select(Team).order_by(Team.id)).all()
        return [_team_out(team) for team in teams]


@router.patch("/teams/{team_id}")
def update_team(team_id: int, body: TeamUpdate):
    with SessionLocal() as session:
        team = _get_team(session, team_id)
        for field in body.model_fields_set:
            setattr(team, field, getattr(body, field))
        session.commit()
        return _team_out(team)


@router.post("/teams/{team_id}/keys", status_code=201)
def create_key(team_id: int, body: KeyCreate):
    """Issue a new key. The full key is in this response only; it can't be shown again."""
    with SessionLocal() as session:
        _get_team(session, team_id)

    key, plain = auth.issue_key(team_id, body.name)
    return {**_key_out(key), "key": plain, "note": "Store this key now; it won't be shown again."}


@router.get("/teams/{team_id}/keys")
def list_keys(team_id: int):
    with SessionLocal() as session:
        _get_team(session, team_id)
        keys = session.scalars(select(ApiKey).where(ApiKey.team_id == team_id)).all()
        return [_key_out(key) for key in keys]


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int):
    """Revoke a key. It stops working immediately; past usage stays in the logs."""
    if not auth.revoke_key(key_id):
        raise HTTPException(status_code=404, detail=f"Key {key_id} not found.")
    return {"revoked": key_id}


def _get_team(session, team_id: int) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team {team_id} not found.")
    return team


def _team_out(team: Team) -> dict:
    context = TeamContext(
        team_id=team.id,
        team_name=team.name,
        key_id=0,
        monthly_budget_usd=team.monthly_budget_usd,
        rate_limit_per_minute=team.rate_limit_per_minute,
    )
    return {
        "id": team.id,
        "name": team.name,
        "rate_limit_per_minute": team.rate_limit_per_minute,
        "created_at": team.created_at,
        **budget_status(context),
    }


def _key_out(key: ApiKey) -> dict:
    # Never includes the hash or the key itself.
    return {
        "id": key.id,
        "team_id": key.team_id,
        "name": key.name,
        "prefix": key.key_prefix,
        "created_at": key.created_at,
        "revoked_at": key.revoked_at,
    }
