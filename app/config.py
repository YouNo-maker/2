from __future__ import annotations
from typing import Any, Dict
from pathlib import Path
import os
import yaml


_DEFAULT_CONFIG_PATH = Path("config/config.yaml")


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> Dict[str, Any]:
    path = os.getenv("APP_CONFIG_PATH") or str(_DEFAULT_CONFIG_PATH)
    base: Dict[str, Any] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            base = yaml.safe_load(f) or {}
    except Exception:
        base = {}
    # Environment overrides for simple keys can be added here if needed
    return base



def get_config() -> Dict[str, Any]:
    return load_config()



def get_db_path() -> str:
    """Return SQLite DB path from config or default to ./data/app.db.
    Supports config key `storage.db_path` and normalizes to string path.
    """
    cfg = load_config()
    storage_cfg = cfg.get("storage") or {}
    db_path = storage_cfg.get("db_path") or "data/app.db"
    return str(Path(db_path))


def get_db_url() -> str | None:
    """Return an explicit DB URL if provided via env or config, else None.
    Priority: env DATABASE_URL > config storage.db_url.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url and isinstance(env_url, str) and env_url.strip():
        return env_url.strip()
    cfg = load_config()
    storage_cfg = cfg.get("storage") or {}
    url = storage_cfg.get("db_url")
    if url and isinstance(url, str) and url.strip():
        return url.strip()
    return None


def get_llm_config() -> Dict[str, Any]:
    """Return LLM configuration merged with environment overrides.
    Recognizes env: DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, LLM_TEMPERATURE, LLM_TIMEOUT_MS.
    """
    cfg = load_config()
    llm = dict(cfg.get("llm") or {})
    # Standardize keys
    provider = (llm.get("provider") or os.getenv("LLM_PROVIDER") or "deepseek").lower()
    temperature = llm.get("temperature")
    timeout_ms = llm.get("timeout_ms")
    # Env overrides
    try:
        if os.getenv("LLM_TEMPERATURE") is not None:
            temperature = float(os.getenv("LLM_TEMPERATURE"))
    except Exception:
        pass
    try:
        if os.getenv("LLM_TIMEOUT_MS") is not None:
            timeout_ms = int(os.getenv("LLM_TIMEOUT_MS"))
    except Exception:
        pass
    api_key = os.getenv("DEEPSEEK_API_KEY") or llm.get("api_key")
    base_url = os.getenv("DEEPSEEK_BASE_URL") or llm.get("base_url") or "https://api.deepseek.com"
    return {
        "provider": provider,
        "temperature": temperature if temperature is not None else 0.3,
        "timeout_ms": timeout_ms if timeout_ms is not None else 12000,
        "api_key": api_key,
        "base_url": base_url,
    } 