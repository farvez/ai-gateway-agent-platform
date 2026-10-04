def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_chat_success(client):
    # Arrange
    payload = {"provider": "fake", "message": "hi"}

    # Act
    response = client.post("/chat", json=payload)

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "echo: hi"
    assert body["usage"]["total_tokens"] == 3


def test_chat_custom_model(client):
    payload = {"provider": "fake", "message": "hi", "model": "my-model"}

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["model"] == "my-model"


def test_unknown_provider_returns_400(client):
    payload = {"provider": "banana", "message": "hi"}

    response = client.post("/chat", json=payload)

    assert response.status_code == 400
    assert "Unsupported provider" in response.json()["detail"]


def test_provider_failure_returns_502(client):
    payload = {"provider": "broken", "message": "hi"}

    response = client.post("/chat", json=payload)

    assert response.status_code == 502
    assert "upstream is down" in response.json()["detail"]


def test_chat_with_fallback(client):
    payload = {"provider": "broken", "message": "hi", "fallbacks": ["fake"]}

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    routing = response.json()["routing"]
    assert routing["served_by"] == "fake"
    assert routing["fallback_used"] is True


def test_chat_retries_flaky_provider(client):
    payload = {"provider": "flaky", "message": "hi"}

    response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["routing"]["attempts"] == 3


def test_unknown_fallback_returns_400(client):
    payload = {"provider": "fake", "message": "hi", "fallbacks": ["banana"]}

    response = client.post("/chat", json=payload)

    assert response.status_code == 400
