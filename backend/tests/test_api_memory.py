import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

def test_get_user_profile():
    response = client.get("/api/user/profile?user_id=test_api_user")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["profile"]["user_id"] == "test_api_user"
    assert data["profile"]["risk_tolerance"] == "medium"

def test_update_user_profile():
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

def test_watchlist_endpoints():
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
