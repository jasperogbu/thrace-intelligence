#!/usr/bin/env python3
"""Run a full venture pipeline test against the local API, saving SSE events."""
import json
import sys
import urllib.request

IDEA = sys.argv[1] if len(sys.argv) > 1 else "Start a food processing business in Jos, Nigeria"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/jaspa_venture_run.sse"

req = urllib.request.Request(
    "http://localhost:8000/api/venture",
    data=json.dumps({"idea": IDEA}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)

events = {"stage_start": 0, "stage_done": 0, "delta": 0, "done": 0, "error": 0}
report_len = 0
err_msg = None

with urllib.request.urlopen(req, timeout=900) as resp, open(OUT, "w") as f:
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        f.write(line + "\n")
        f.flush()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except Exception:
            continue
        t = ev.get("type")
        if t in events:
            events[t] += 1
        if t == "delta":
            report_len += len(ev.get("data", ""))
        if t == "error":
            err_msg = ev.get("message", "")

print(json.dumps({"events": events, "report_chars": report_len, "error": err_msg}, indent=2))
