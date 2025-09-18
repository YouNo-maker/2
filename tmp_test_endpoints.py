from app.server import app
from fastapi.testclient import TestClient

client = TestClient(app)

resp = client.get("/v1/health")
print("HEALTH_STATUS_CODE", resp.status_code)

resp = client.get("/v1/health", params={"verbose": 1})
print("HEALTH_VERBOSE", resp.json())

resp = client.get("/v1/alerts")
print("ALERTS", resp.json())

resp = client.get("/v1/intraday/status")
print("INTRADAY_STATUS", resp.json())

resp = client.post("/v1/intraday/start")
print("INTRADAY_START", resp.json())

resp = client.get("/v1/intraday/status")
print("INTRADAY_STATUS_AFTER_START", resp.json())

resp = client.post("/v1/intraday/stop")
print("INTRADAY_STOP", resp.json()) 