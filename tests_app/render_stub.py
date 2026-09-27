"""Stand-in renderer child for SubprocessRenderer tests (no Node, no browser)."""
import json
import os
import sys
import time

payload = json.loads(sys.stdin.read())
layout = payload.get("layout")
if layout == "BAD_INPUT":
    sys.stderr.write("unknown_layout\n")
    sys.exit(2)
if layout == "CRASH":
    sys.stderr.write("Traceback: something /secret/path\n")
    sys.exit(1)
if layout == "SLOW":
    time.sleep(5)
sys.stdout.buffer.write(b"%PDF-" + json.dumps({"input": payload, "env": sorted(os.environ)}).encode())
