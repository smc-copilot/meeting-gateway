"""Opt-in live checks. They skip unless MEETING_LIVE=1 and never embed credentials."""
import os
import pytest

pytestmark = pytest.mark.live


def _skip_without_live():
    if os.environ.get("MEETING_LIVE") != "1":
        pytest.skip("MEETING_LIVE is not 1; real Tencent calls were not executed")


def test_tencent_aksk_live_smoke():
    _skip_without_live()
    pytest.skip("Live AK/SK call is operator-run; this checkout does not contact Tencent")


def test_tencent_oauth_live_smoke():
    _skip_without_live()
    pytest.skip("Live OAuth call is operator-run; this checkout does not contact Tencent")


def test_tencent_content_live_smoke():
    _skip_without_live()
    pytest.skip("Live content call is operator-run; this checkout does not contact Tencent")
