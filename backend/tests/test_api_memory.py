import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from backend.api.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_get_user_profile(client):
    response = client.get("/api/user/profile?user_id=test_api_user")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["profile"]["user_id"] == "test_api_user"
    assert data["profile"]["risk_tolerance"] == "medium"

def test_update_user_profile(client):
    # Update profile
    profile_update = {
        "user_id": "test_api_user",
        "profile": {
            "risk_tolerance": "aggressive",
            "investment_style": "growth"
        }
    }
    response = client.post("/api/user/profile", json=profile_update)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify update
    response = client.get("/api/user/profile?user_id=test_api_user")
    data = response.json()
    assert data["profile"]["risk_tolerance"] == "aggressive"
    assert data["profile"]["investment_style"] == "growth"

def test_watchlist_endpoints(client):
    user_id = "test_api_user_wl"

    # Add to watchlist
    response = client.post("/api/user/watchlist/add", json={"user_id": user_id, "ticker": "NVDA"})
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify add
    response = client.get(f"/api/user/profile?user_id={user_id}")
    data = response.json()
    assert "NVDA" in data["profile"]["watchlist"]

    # Remove from watchlist
    response = client.post("/api/user/watchlist/remove", json={"user_id": user_id, "ticker": "NVDA"})
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Verify remove
    response = client.get(f"/api/user/profile?user_id={user_id}")
    data = response.json()
    assert "NVDA" not in data["profile"]["watchlist"]


def test_agent_preferences_endpoints(client):
    user_id = f"test_api_user_agent_prefs_{uuid4().hex}"

    # Get defaults
    response = client.get(f"/api/agents/preferences?user_id={user_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["preferences"]["maxRounds"] == 3
    assert data["preferences"]["concurrentMode"] is True
    assert data["preferences"]["agents"]["price_agent"] == "standard"

    # Update with mixed valid/invalid payload
    update_payload = {
        "user_id": user_id,
        "preferences": {
            "agents": {
                "news_agent": "deep",
                "technical_agent": "off",
                "unknown_agent": "off",
            },
            "maxRounds": 99,
            "concurrentMode": False,
        },
    }
    response = client.put("/api/agents/preferences", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["preferences"]["maxRounds"] == 10
    assert data["preferences"]["concurrentMode"] is False
    assert data["preferences"]["agents"]["news_agent"] == "deep"
    assert data["preferences"]["agents"]["technical_agent"] == "off"
    assert "unknown_agent" not in data["preferences"]["agents"]

    # Verify persistence
    response = client.get(f"/api/agents/preferences?user_id={user_id}")
    data = response.json()
    assert data["success"] is True
    assert data["preferences"]["agents"]["news_agent"] == "deep"
    assert data["preferences"]["agents"]["technical_agent"] == "off"
