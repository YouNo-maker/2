from __future__ import annotations
import time
from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def test_e2e_pipeline_run_then_query_topn_and_plan():
	trade_date = "2025-09-10"
	body = {"market": "SSE", "trade_date": trade_date, "dedupe_key": f"E2E_SSE_{trade_date}"}
	resp = client.post("/v1/pipeline/preopen/run", json=body)
	assert resp.status_code == 202
	tid = resp.json()["task_id"]

	# Poll status until completed (quick synchronous pipeline in background thread)
	status = None
	for _ in range(200):
		st = client.get(f"/v1/pipeline/preopen/status?task_id={tid}")
		assert st.status_code == 200
		data = st.json()
		status = data.get("status")
		if status in ("completed", "failed"):
			break
		time.sleep(0.02)

	assert status == "completed"

	# TopN should be available for the date/market
	topn = client.get("/v1/news/topn", params={"market": "SSE", "as_of": f"{trade_date}T10:00:00Z", "n": 5})
	assert topn.status_code == 200
	tdata = topn.json()
	assert tdata["market"] == "SSE"
	assert tdata["topn"] and len(tdata["topn"]) >= 1
	first = tdata["topn"][0]
	assert "symbol" in first and "code" in first["symbol"]
	assert "aggregate_score" in first and first["aggregate_score"] >= 0.0

	# Plan should be persisted (poll for readiness)
	pdata = None
	for _ in range(100):
		plan = client.get("/v1/plan/latest", params={"trade_date": trade_date, "market": "SSE"})
		if plan.status_code == 200:
			pdata = plan.json()
			break
		time.sleep(0.02)
	assert pdata is not None
	assert pdata["trade_date"] == trade_date
	assert pdata["market"] == "SSE"
	assert isinstance(pdata.get("plan_json"), dict) and "entries" in pdata["plan_json"] 