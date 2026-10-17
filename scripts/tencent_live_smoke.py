#!/usr/bin/env python3
"""Read-only gateway smoke. It calls the deployed Meeting API, not Tencent directly.

Credentials stay in the process environment. The report keeps status and resource ids.
It never prints secrets, tokens or signed download URLs.
"""
import json
import os
import sys
import urllib.error
import urllib.request


def enabled():
    return os.environ.get("MEETING_LIVE") == "1"


def report(step, **fields):
    allowed = {"status", "upstream_code", "resource_id", "pages", "elapsed_ms", "reason", "database", "backend"}
    safe = {key: fields[key] for key in fields if key in allowed and not _secret(fields[key])}
    print(json.dumps({"step": step, **safe}, ensure_ascii=False))


def _secret(value):
    text = str(value)
    return "token" in text.lower() or "secret" in text.lower() or "Bearer " in text


def _get(url, token):
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def main():
    if not enabled():
        print("MEETING_LIVE is not 1; no gateway call was made.")
        return 0
    if os.environ.get("MEETING_LIVE_WRITE") == "1":
        print("Write mode is explicit. This helper still refuses to create meetings.")
    missing = [name for name in ("MEETING_BASE_URL", "MEETING_ACCESS_TOKEN") if not os.environ.get(name)]
    if missing:
        report("config", status="NOT_RUN", reason="MISSING_ENVIRONMENT")
        return 2
    base = os.environ["MEETING_BASE_URL"].rstrip("/")
    token = os.environ["MEETING_ACCESS_TOKEN"]
    try:
        status, payload = _get(base + "/health/ready", token)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        report("gateway", status="FAILED", reason="GATEWAY_UNREACHABLE")
        return 1
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    if isinstance(payload, dict) and "database" in payload:
        data = payload
    if status != 200 or data.get("database") is not True:
        report("ready", status="FAILED", reason="DATABASE_NOT_READY", database=bool(data.get("database")), backend=bool(data.get("backend")))
        return 1
    report("ready", status="PASSED", database=True, backend=bool(data.get("backend")))
    meeting_id = os.environ.get("MEETING_ID")
    if meeting_id:
        try:
            read_status, read_payload = _get(base + "/api/v1/meetings/" + meeting_id + "?fetch=cache", token)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            report("meeting", status="FAILED", reason="GATEWAY_UNREACHABLE", resource_id=meeting_id)
            return 1
        if read_status != 200:
            report("meeting", status="FAILED", reason="MEETING_NOT_READ", resource_id=meeting_id)
            return 1
        report("meeting", status="PASSED", resource_id=meeting_id)
        body = read_payload.get("data") if isinstance(read_payload, dict) else None
        if isinstance(body, dict) and body.get("id") != meeting_id:
            report("meeting", status="FAILED", reason="RESOURCE_MISMATCH", resource_id=meeting_id)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
