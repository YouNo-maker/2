import json
from fastapi.testclient import TestClient

from app.server import app


client = TestClient(app)


def test_health_ok():
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_preopen_run_accepts_and_returns_deadlines():
    body = {
        "market": "SSE",
        "trade_date": "2025-09-10",
        "dedupe_key": "SSE_2025-09-10"
    }
    resp = client.post("/v1/pipeline/preopen/run", json=body)
    # FastAPI will return 202 as configured
    assert resp.status_code == 202
    data = resp.json()

    assert data["task_id"] == "preopen_SSE_2025-09-10"
    assert data["status"] == "pending"

    deadlines = data["deadlines"]
    # String T-xx markers
    assert deadlines["fetch"] == "T-45"
    assert deadlines["topn"] == "T-35"
    assert deadlines["plan"] == "T-30"
    # ISO timestamps exist
    assert "fetch_at" in deadlines and deadlines["fetch_at"].startswith("2025-09-10T")
    assert "topn_at" in deadlines and deadlines["topn_at"].startswith("2025-09-10T")
    assert "plan_at" in deadlines and deadlines["plan_at"].startswith("2025-09-10T")

    # Follow-up status
    status = client.get(f"/v1/pipeline/preopen/status?task_id={data['task_id']}")
    assert status.status_code == 200
    s = status.json()
    assert s["task_id"] == data["task_id"]
    assert s["status"] in ("running", "pending", "completed")
    assert s["stage"] in (None, "Scheduler")


def test_preopen_run_dedupe_returns_existing_task():
    body = {
        "market": "SSE",
        "trade_date": "2025-09-10",
        "dedupe_key": "SSE_2025-09-10"
    }
    first = client.post("/v1/pipeline/preopen/run", json=body)
    assert first.status_code == 202
    first_id = first.json()["task_id"]

    # Same dedupe_key, not force_recompute → should return existing task id
    second = client.post("/v1/pipeline/preopen/run", json=body)
    assert second.status_code == 202
    assert second.json()["task_id"] == first_id


def test_preopen_retry_creates_new_task_and_links_to_original():
    body = {
        "market": "SSE",
        "trade_date": "2025-09-11",
        "dedupe_key": "SSE_2025-09-11"
    }
    # create original
    resp = client.post("/v1/pipeline/preopen/run", json=body)
    assert resp.status_code == 202
    orig_id = resp.json()["task_id"]

    # retry
    retry_resp = client.post("/v1/pipeline/preopen/retry", json={"task_id": orig_id})
    assert retry_resp.status_code == 202
    retry_data = retry_resp.json()

    assert retry_data["task_id"].startswith(orig_id + "_retry")
    assert retry_data["status"] == "pending"
    assert "deadlines" in retry_data

    # status should be available for new id
    status = client.get(f"/v1/pipeline/preopen/status?task_id={retry_data['task_id']}")
    assert status.status_code == 200
    s = status.json()
    assert s["task_id"] == retry_data["task_id"] 


def test_preopen_jobs_list_and_detail_and_cancel():
    # start a job
    body = {"market": "SSE", "trade_date": "2025-09-12", "dedupe_key": "SSE_2025-09-12"}
    r = client.post("/v1/pipeline/preopen/run", json=body)
    assert r.status_code == 202
    tid = r.json()["task_id"]

    # list
    lst = client.get("/v1/pipeline/preopen/jobs")
    assert lst.status_code == 200
    jobs = lst.json()["jobs"]
    assert any(j["task_id"] == tid for j in jobs)

    # detail
    detail = client.get(f"/v1/pipeline/preopen/job?task_id={tid}")
    assert detail.status_code == 200
    assert detail.json()["task_id"] == tid

    # cancel
    cancel = client.post("/v1/pipeline/preopen/cancel", json={"task_id": tid})
    assert cancel.status_code == 200
    c = cancel.json()
    assert c["task_id"] == tid
    assert c["accepted"] in (True, False)

    # if accepted, status should become failed or remain completed
    st = client.get(f"/v1/pipeline/preopen/status?task_id={tid}")
    assert st.status_code == 200
    s = st.json()
    assert s["status"] in ("running", "failed", "completed") 