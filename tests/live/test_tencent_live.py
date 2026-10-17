"""Opt-in live checks. They call the deployed gateway only when the operator sets MEETING_LIVE=1."""
import os
import importlib.util
from pathlib import Path
import pytest

pytestmark = pytest.mark.live


def _smoke():
    path = Path(__file__).resolve().parents[2] / "scripts" / "tencent_live_smoke.py"
    spec = importlib.util.spec_from_file_location("tencent_live_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_live_gateway():
    if os.environ.get("MEETING_LIVE") != "1":
        pytest.skip("MEETING_LIVE is not 1; no gateway call was made")
    if not os.environ.get("MEETING_BASE_URL") or not os.environ.get("MEETING_ACCESS_TOKEN"):
        pytest.skip("BLOCKED: MEETING_BASE_URL or MEETING_ACCESS_TOKEN is missing; this is not a pass")


def test_tencent_aksk_live_smoke():
    _require_live_gateway()
    assert _smoke().main() == 0


def test_tencent_oauth_live_smoke():
    _require_live_gateway()
    assert _smoke().main() == 0


def test_tencent_content_live_smoke():
    _require_live_gateway()
    if not os.environ.get("MEETING_ID"):
        pytest.skip("BLOCKED: MEETING_ID is missing; content smoke is not a pass")
    assert _smoke().main() == 0
