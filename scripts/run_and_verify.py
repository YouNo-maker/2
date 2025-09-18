import sys
import time
import json
import socket
import subprocess
from typing import Tuple
import os


def _wait_port(host: str, port: int, timeout_s: float) -> bool:
	deadline = time.time() + timeout_s
	while time.time() < deadline:
		try:
			with socket.create_connection((host, port), timeout=0.5):
				return True
		except OSError:
			time.sleep(0.2)
	return False


def _http_get(url: str, timeout: float = 1.5):
	import httpx
	try:
		with httpx.Client(timeout=timeout) as client:
			resp = client.get(url)
			return {"ok": True, "status_code": resp.status_code, "json": resp.json()}
	except Exception as exc:  # pragma: no cover
		return {"ok": False, "error": str(exc)}


def _http_post(url: str, timeout: float = 1.5):
	import httpx
	try:
		with httpx.Client(timeout=timeout) as client:
			resp = client.post(url)
			return {"ok": True, "status_code": resp.status_code, "json": resp.json()}
	except Exception as exc:  # pragma: no cover
		return {"ok": False, "error": str(exc)}


def _start_server() -> Tuple[subprocess.Popen, str]:
	cmd = [sys.executable, "-m", "uvicorn", "app.server:app", "--host", "127.0.0.1", "--port", "8010", "--log-level", "warning"]
	env = dict(os.environ)
	env.setdefault("DISABLE_SCHEDULER", "1")
	env.setdefault("PREOPEN_JSON_LOGS", "1")
	proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
	return proc, "127.0.0.1:8010"


def main() -> int:
	proc, addr = _start_server()
	try:
		listening = _wait_port("127.0.0.1", 8010, timeout_s=15)
		print("LISTENING=", listening, flush=True)
		if not listening:
			# Try to collect a small slice of stderr without blocking
			try:
				proc.terminate()
			except Exception:
				pass
			stderr = ""
			try:
				out, err = proc.communicate(timeout=3)
				stderr = (err or b"").decode(errors="ignore")
			except Exception:
				try:
					stderr = (proc.stderr.read(4000) if proc.stderr else b"").decode(errors="ignore")
				except Exception:
					stderr = ""
			print("SERVER_ERR=", json.dumps(stderr[-4000:]), flush=True)
			return 3

		health = _http_get("http://127.0.0.1:8010/v1/health")
		print("HEALTH=", json.dumps(health), flush=True)
		if not (health.get("ok") and health.get("status_code") == 200 and health.get("json", {}).get("status") == "ok"):
			return 2

		status_before = _http_get("http://127.0.0.1:8010/v1/scheduler/status")
		print("SCHEDULER_STATUS_BEFORE=", json.dumps(status_before), flush=True)

		start_res = _http_post("http://127.0.0.1:8010/v1/scheduler/start?force=1")
		print("SCHEDULER_START=", json.dumps(start_res), flush=True)

		status_after = _http_get("http://127.0.0.1:8010/v1/scheduler/status")
		print("SCHEDULER_STATUS_AFTER=", json.dumps(status_after), flush=True)

		return 0
	finally:
		try:
			proc.terminate()
			t0 = time.time()
			while proc.poll() is None and time.time() - t0 < 3:
				time.sleep(0.1)
			if proc.poll() is None:
				proc.kill()
		except Exception:
			pass


if __name__ == "__main__":
	sys.exit(main()) 