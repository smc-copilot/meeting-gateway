"""Phase-1 live acceptance stays blocked until an allowlisted egress binding exists."""
from pathlib import Path
import pytest

pytestmark = pytest.mark.live


def test_dual_channel_read():
    binding = Path(__file__).resolve().parents[2] / "deploy" / "bindings" / "golden-consumer.json"
    if not binding.is_file():
        pytest.skip("BLOCKED: golden consumer binding is missing; this is not a pass")
    pytest.skip("BLOCKED: allowlisted egress is not evidenced in this checkout")


def test_trusted_member_create():
    pytest.skip("BLOCKED: live create runs only from the designated egress host")


def test_oauth_content_download_and_events():
    pytest.skip("BLOCKED: live content, download and signed events are not run from this machine")
