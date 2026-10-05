import sqlite3

import pytest
from sqlalchemy import inspect

from app import auth, config, db, usage
from app.limits import RateLimiter
from app.models import ApiKey
from tests.conftest import ADMIN_HEADERS, create_team, key_headers

CHAT = {"provider": "fake", "message": "hi"}
# FakeProvider uses 1 input + 2 output tokens; with this model name the price table applies.
PRICED = {"provider": "fake", "message": "hi", "model": "gpt-4o-mini"}


# ---------- authentication ----------


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_missing_key_is_rejected(anon_client, path):
    response = anon_client.post(path, json=CHAT)

    assert response.status_code == 401
    assert "Missing API key" in response.json()["detail"]


def test_wrong_key_is_rejected(anon_client):
    response = anon_client.post(
        "/chat", json=CHAT, headers={"Authorization": "Bearer gw-not-a-real-key"}
    )

    assert response.status_code == 401


def test_revoked_key_is_rejected(anon_client, team_id):
    key_row, plain = auth.issue_key(team_id)
    headers = {"Authorization": f"Bearer {plain}"}
    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 200

    auth.revoke_key(key_row.id)

    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 401


def test_keys_are_stored_hashed(team_id):
    key_row, plain = auth.issue_key(team_id)

    assert plain.startswith("gw-")
    assert key_row.key_hash == auth.hash_key(plain)
    assert plain not in (key_row.key_hash, key_row.key_prefix)


def test_public_endpoints_need_no_key(anon_client):
    assert anon_client.get("/health").status_code == 200
    assert anon_client.get("/demo").status_code == 200


def test_requests_are_recorded_against_the_team(client, team_id):
    client.post("/chat", json=CHAT)

    [row] = client.get("/usage/recent", headers=ADMIN_HEADERS).json()
    assert row["team_id"] == team_id


# ---------- admin API ----------


def test_admin_endpoints_need_the_admin_key(client):
    # A team key is not an admin key.
    assert client.get("/admin/teams").status_code == 401
    assert client.get("/usage").status_code == 401
    assert client.get("/admin/teams", headers=ADMIN_HEADERS).status_code == 200


def test_admin_disabled_without_admin_key(anon_client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY")

    assert anon_client.get("/admin/teams", headers=ADMIN_HEADERS).status_code == 503


def test_admin_onboards_a_team_end_to_end(anon_client):
    # 1. Create a team with a budget and a rate limit.
    response = anon_client.post(
        "/admin/teams",
        json={"name": "search", "monthly_budget_usd": 50, "rate_limit_per_minute": 100},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 201
    team = response.json()
    assert team["remaining_usd"] == 50

    # 2. Issue a key. The full key appears in this response only.
    response = anon_client.post(
        f"/admin/teams/{team['id']}/keys", json={"name": "backend"}, headers=ADMIN_HEADERS
    )
    assert response.status_code == 201
    key = response.json()["key"]

    # 3. The team can use the gateway with it.
    headers = {"Authorization": f"Bearer {key}"}
    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 200

    # 4. Listing keys never shows the key or its hash.
    [listed] = anon_client.get(f"/admin/teams/{team['id']}/keys", headers=ADMIN_HEADERS).json()
    assert key not in str(listed)
    assert "key_hash" not in listed

    # 5. Revoking it locks the team out immediately.
    anon_client.delete(f"/admin/keys/{listed['id']}", headers=ADMIN_HEADERS)
    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 401


def test_duplicate_team_name_is_rejected(anon_client):
    anon_client.post("/admin/teams", json={"name": "search"}, headers=ADMIN_HEADERS)

    response = anon_client.post("/admin/teams", json={"name": "search"}, headers=ADMIN_HEADERS)

    assert response.status_code == 409


def test_admin_can_change_and_remove_limits(anon_client, team_id):
    url = f"/admin/teams/{team_id}"

    updated = anon_client.patch(url, json={"monthly_budget_usd": 10}, headers=ADMIN_HEADERS)
    assert updated.json()["monthly_budget_usd"] == 10

    removed = anon_client.patch(url, json={"monthly_budget_usd": None}, headers=ADMIN_HEADERS)
    assert removed.json()["monthly_budget_usd"] is None


def test_unknown_team_is_404(anon_client):
    response = anon_client.post("/admin/teams/999/keys", json={}, headers=ADMIN_HEADERS)

    assert response.status_code == 404


# ---------- rate limiting ----------


def test_rate_limit(anon_client):
    headers = key_headers(create_team("limited", rate_limit_per_minute=2))

    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 200
    assert anon_client.post("/chat", json=CHAT, headers=headers).status_code == 200
    response = anon_client.post("/chat", json=CHAT, headers=headers)

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_rate_limit_is_per_team(anon_client):
    busy = key_headers(create_team("busy", rate_limit_per_minute=1))
    other = key_headers(create_team("other", rate_limit_per_minute=1))

    anon_client.post("/chat", json=CHAT, headers=busy)

    assert anon_client.post("/chat", json=CHAT, headers=busy).status_code == 429
    assert anon_client.post("/chat", json=CHAT, headers=other).status_code == 200


def test_rate_limiter_window_slides():
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])

    assert limiter.check(1, limit=2) is None
    assert limiter.check(1, limit=2) is None
    assert limiter.check(1, limit=2) == pytest.approx(60.0)  # wait for the oldest to expire

    now[0] = 60.0  # one minute later the first two requests have left the window
    assert limiter.check(1, limit=2) is None


# ---------- budgets ----------


def test_budget_blocks_requests_once_spent(anon_client):
    # One priced request costs $0.00000135, so this budget covers exactly one.
    headers = key_headers(create_team("tight", monthly_budget_usd=0.000001))

    assert anon_client.post("/chat", json=PRICED, headers=headers).status_code == 200
    response = anon_client.post("/chat", json=PRICED, headers=headers)

    # 402, not 429: retrying won't help until the budget is raised.
    assert response.status_code == 402
    assert "Monthly budget" in response.json()["detail"]


def test_budget_also_blocks_streaming(anon_client):
    headers = key_headers(create_team("tight", monthly_budget_usd=0.000001))
    anon_client.post("/chat", json=PRICED, headers=headers)

    assert anon_client.post("/chat/stream", json=PRICED, headers=headers).status_code == 402


def test_raising_the_budget_unblocks(anon_client):
    team = create_team("tight", monthly_budget_usd=0.000001)
    headers = key_headers(team)
    anon_client.post("/chat", json=PRICED, headers=headers)

    anon_client.patch(f"/admin/teams/{team}", json={"monthly_budget_usd": 5}, headers=ADMIN_HEADERS)

    assert anon_client.post("/chat", json=PRICED, headers=headers).status_code == 200


def test_budget_only_counts_this_team(anon_client):
    spender = key_headers(create_team("spender"))
    saver = key_headers(create_team("saver", monthly_budget_usd=0.000001))

    for _ in range(3):
        anon_client.post("/chat", json=PRICED, headers=spender)

    assert anon_client.post("/chat", json=PRICED, headers=saver).status_code == 200


# ---------- /me ----------


def test_me_shows_budget_and_usage(anon_client):
    headers = key_headers(create_team("search", monthly_budget_usd=1.0))
    anon_client.post("/chat", json=PRICED, headers=headers)

    me = anon_client.get("/me", headers=headers).json()

    assert me["team"]["name"] == "search"
    assert me["budget"]["spent_this_month_usd"] == pytest.approx(0.00000135)
    assert me["budget"]["remaining_usd"] == pytest.approx(1.0 - 0.00000135)
    assert me["usage_this_month"]["totals"]["requests"] == 1


def test_me_only_shows_own_team(anon_client):
    mine = key_headers(create_team("mine"))
    theirs = key_headers(create_team("theirs"))
    anon_client.post("/chat", json=CHAT, headers=theirs)

    me = anon_client.get("/me", headers=mine).json()

    assert me["usage_this_month"]["totals"]["requests"] == 0


def test_usage_by_team(anon_client):
    search = key_headers(create_team("search"))
    support = key_headers(create_team("support"))
    anon_client.post("/chat", json=CHAT, headers=search)
    anon_client.post("/chat", json=CHAT, headers=search)
    anon_client.post("/chat", json=CHAT, headers=support)

    by_team = anon_client.get("/usage", headers=ADMIN_HEADERS).json()["by_team"]

    assert {row["team"]: row["requests"] for row in by_team} == {"search": 2, "support": 1}


# ---------- guardrails ----------


def test_empty_message_is_rejected(client):
    assert client.post("/chat", json={"provider": "fake", "message": ""}).status_code == 422


def test_oversized_message_is_rejected(client):
    too_long = "x" * (config.max_input_chars() + 1)

    response = client.post("/chat", json={"provider": "fake", "message": too_long})

    assert response.status_code == 422


def test_output_cap_is_configurable(monkeypatch):
    assert config.max_output_tokens() == 1024

    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "256")
    assert config.max_output_tokens() == 256


# ---------- schema upgrade ----------


def test_old_database_gets_new_columns(tmp_path):
    # A database created before Phase 5: request_logs without team_id.
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE request_logs (id INTEGER PRIMARY KEY, created_at DATETIME, "
        "endpoint VARCHAR(20), status VARCHAR(20), requested_provider VARCHAR(50), "
        "served_by VARCHAR(50), model VARCHAR(100), fallback_used BOOLEAN, attempts INTEGER, "
        "input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, cost_usd FLOAT, "
        "latency_ms INTEGER, ttft_ms INTEGER, error TEXT)"
    )
    connection.commit()
    connection.close()

    engine = db.configure(f"sqlite:///{path}")

    columns = {c["name"] for c in inspect(engine).get_columns("request_logs")}
    assert "team_id" in columns
    assert inspect(engine).has_table("api_keys")

    # And logging works against the upgraded table.
    usage.record_request(endpoint="chat", status="success", requested_provider="x", latency_ms=1)
    assert usage.recent()[0]["team_id"] is None
    engine.dispose()


def test_api_key_hash_column_is_unique(database):
    assert ApiKey.__table__.c.key_hash.unique
