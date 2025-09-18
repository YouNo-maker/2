from __future__ import annotations
import pytest
from app.pipeline.preopen import PreOpenPipeline
from app.models import DeadlinesSpec


def test_pipeline_run_produces_topn_and_plan():
	try:
		from app.storage import get_session, TopCandidate, TradePlan
	except Exception:
		pytest.skip("storage not available; skipping pipeline produce data test")

	res = PreOpenPipeline.run("SSE", "2025-09-10", DeadlinesSpec(fetch_min_before_open=45, topn_min_before_open=35, plan_min_before_open=30))
	assert res["task_id"].startswith("preopen_SSE_2025-09-10")

	with get_session() as session:
		# There should be at least one TopCandidate and one TradePlan
		topn = session.exec(TopCandidate.__table__.select()).all()  # type: ignore
		plans = session.exec(TradePlan.__table__.select()).all()  # type: ignore
		assert len(topn) >= 1
		assert len(plans) >= 1 