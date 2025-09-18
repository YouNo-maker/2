from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
import os
import sys
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from ..config import get_db_path, get_db_url

# Determine DB URL: in pytest use in-memory to ensure isolation
_IN_PYTEST = bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)
_DB_URL: str

if _IN_PYTEST:
	# Use a single shared in-memory DB across threads/connections
	_DB_URL = "sqlite://"
	_ENGINE = create_engine(
		_DB_URL,
		echo=False,
		connect_args={"check_same_thread": False},
		poolclass=StaticPool,
	)
else:
	# Prefer explicit DATABASE_URL, then config storage.db_url, else fallback to SQLite file path
	_configured_url = get_db_url()
	if _configured_url:
		_DB_URL = _configured_url
		_ENGINE = create_engine(_DB_URL, echo=False)
	else:
		_DB_PATH = Path(get_db_path())
		_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
		_DB_URL = f"sqlite:///{_DB_PATH}"
		_ENGINE = create_engine(_DB_URL, echo=False)


def init_db() -> None:
	# Ensure models are imported so SQLModel.metadata is populated
	from . import models as _models  # noqa: F401
	# When under pytest, ensure a clean slate
	if _IN_PYTEST:
		try:
			SQLModel.metadata.drop_all(_ENGINE)
		except Exception:
			pass
	SQLModel.metadata.create_all(_ENGINE)
	# Lightweight migrations (SQLite): add newly introduced columns if missing
	try:
		with _ENGINE.connect() as conn:
			dialect_name = _ENGINE.dialect.name
			if dialect_name == "sqlite":
				# normalizednews: content_hash, link_canon_hash
				res = conn.exec_driver_sql("PRAGMA table_info('normalizednews')")
				cols = {str(r[1]) for r in res.fetchall()}  # type: ignore
				if "content_hash" not in cols:
					conn.exec_driver_sql("ALTER TABLE normalizednews ADD COLUMN content_hash TEXT")
				if "link_canon_hash" not in cols:
					conn.exec_driver_sql("ALTER TABLE normalizednews ADD COLUMN link_canon_hash TEXT")
	except Exception:
		# Best-effort; ignore migration errors to avoid breaking startup
		pass


@contextmanager
def get_session() -> Iterator[Session]:
	with Session(_ENGINE) as session:
		yield session 