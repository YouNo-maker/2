import pytest
from fastapi.testclient import TestClient
from app.server import app

client = TestClient(app)


def test_plan_validate_direction_and_rr():
	bad = {
		"trade_date": "2025-09-10",
		"market": "SSE",
		"entries": [
			{"symbol": "AAA", "direction": "LONG", "entry": 100, "stop": 99, "take_profit": 101},  # RR=1
		]
	}
	resp = client.post("/v1/plan/validate", json={"plan": bad})
	assert resp.status_code == 200
	data = resp.json()
	assert data["passed"] is False
	assert any("risk-reward" in e for e in data["issues"])


def test_plan_validate_short_ordering():
	bad = {
		"trade_date": "2025-09-10",
		"market": "SSE",
		"entries": [
			{"symbol": "BBB", "direction": "SHORT", "entry": 100, "stop": 98, "take_profit": 101},
		]
	}
	resp = client.post("/v1/plan/validate", json={"plan": bad})
	assert resp.status_code == 200
	data = resp.json()
	assert data["passed"] is False
	assert any("SHORT requires" in e for e in data["issues"])


def test_plan_validate_good_example():
	good = {
		"trade_date": "2025-09-10",
		"market": "SSE",
		"entries": [
			{"symbol": "AAA", "direction": "LONG", "entry": 100, "stop": 98, "take_profit": 103},
		]
	}
	resp = client.post("/v1/plan/validate", json={"plan": good})
	assert resp.status_code == 200
	data = resp.json()
	assert data["passed"] is True
	assert data["issues"] == [] 