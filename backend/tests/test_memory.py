import pytest
import os
import json
from backend.services.memory import MemoryService, UserProfile

@pytest.fixture
def memory_service(tmp_path):
    # Use a temporary directory for tests
    return MemoryService(storage_path=str(tmp_path))

def test_get_new_profile(memory_service):
    profile = memory_service.get_user_profile("test_user_1")
    assert profile.user_id == "test_user_1"
    assert profile.risk_tolerance == "medium"
    assert profile.investment_style == "balanced"
    assert profile.watchlist == []

def test_update_profile(memory_service):
    profile = memory_service.get_user_profile("test_user_2")
    profile.risk_tolerance = "high"
    profile.investment_style = "aggressive"

    success = memory_service.update_user_profile(profile)
    assert success is True

    # Reload to verify persistence
    loaded_profile = memory_service.get_user_profile("test_user_2")
    assert loaded_profile.risk_tolerance == "high"
    assert loaded_profile.investment_style == "aggressive"

def test_watchlist_operations(memory_service):
    user_id = "test_user_3"

    # Add
    memory_service.add_to_watchlist(user_id, "AAPL")
    profile = memory_service.get_user_profile(user_id)
    assert "AAPL" in profile.watchlist

    # Add Duplicate (should ignore)
    memory_service.add_to_watchlist(user_id, "AAPL")
    profile = memory_service.get_user_profile(user_id)
    assert len(profile.watchlist) == 1

    # Add another
    memory_service.add_to_watchlist(user_id, "MSFT")
    profile = memory_service.get_user_profile(user_id)
    assert "MSFT" in profile.watchlist
    assert len(profile.watchlist) == 2

    # Remove
    memory_service.remove_from_watchlist(user_id, "AAPL")
    profile = memory_service.get_user_profile(user_id)
    assert "AAPL" not in profile.watchlist
    assert "MSFT" in profile.watchlist

def test_preferences(memory_service):
    user_id = "test_user_4"
    memory_service.set_preference(user_id, "theme", "dark")

    profile = memory_service.get_user_profile(user_id)
    assert profile.preferences.get("theme") == "dark"
