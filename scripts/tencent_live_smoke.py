#!/usr/bin/env python3
"""Read-only Tencent smoke helper. Does nothing unless MEETING_LIVE=1 is set.

Credentials stay in the process environment. The report keeps status, upstream code,
resource ids, page counts and elapsed time. It never prints secrets or signed download URLs.
"""
import json
import os
import sys


def enabled():
    return os.environ.get("MEETING_LIVE") == "1"


def report(step, **fields):
    allowed = {"status", "upstream_code", "resource_id", "pages", "elapsed_ms", "reason"}
    safe = {key: fields[key] for key in fields if key in allowed}
    print(json.dumps({"step": step, **safe}, ensure_ascii=False))


def main():
    if not enabled():
        print("MEETING_LIVE is not 1; no Tencent call was made.")
        return 0
    if os.environ.get("MEETING_LIVE_WRITE") == "1":
        print("Write mode is explicit. This helper still refuses to create meetings.")
    missing = [name for name in ("MEETING_BASE_URL", "MEETING_ACCESS_TOKEN") if not os.environ.get(name)]
    if missing:
        report("config", status="NOT_RUN", reason="MISSING_ENVIRONMENT")
        return 2
    report("config", status="NOT_RUN", reason="LIVE_CLIENT_NOT_BUNDLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
