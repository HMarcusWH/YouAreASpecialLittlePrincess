#!/usr/bin/env python3
"""Provider-free external API smoke for application rollback qualification."""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import math
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path
from typing import Any

NOTICE = "notice.consent-choices:1"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", binascii.crc32(kind + payload) & 0xFFFFFFFF
    )


def handwriting_png() -> bytes:
    width, height = 900, 360
    pixels = [bytearray([245]) * width for _ in range(height)]

    def mark(x: int, y: int, radius: int = 2) -> None:
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                pixels[yy][xx] = 28

    for line in range(3):
        base = 72 + line * 105
        for x in range(35, 860):
            wave = int(8 * math.sin(x / 17.0) + 3 * math.sin(x / 5.0))
            mark(x, base + wave, 1)
            if x % 47 < 3:
                for dy in range(-26, 13):
                    mark(x, base + wave + dy, 1)
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return signature + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def request(method: str, url: str, *, token: str | None = None, payload: Any = None, data: bytes | None = None) -> Any:
    headers = {"Accept": "application/json"}
    body = data
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    elif data is not None:
        headers["Content-Type"] = "image/png"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read()
            if not content:
                return None
            return json.loads(content) if "json" in response.headers.get("content-type", "") else content
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {url} -> {exc.code}: {detail[:500]}") from exc


def endpoint(base: str, path: str) -> str:
    return urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def verify_view(view: Any, report_id: str) -> None:
    if not isinstance(view, dict) or view.get("source_report_id") != report_id:
        raise RuntimeError("report read returned the wrong report")
    if not isinstance(view.get("facts"), list) or not isinstance(view.get("sections"), list) or not view["sections"]:
        raise RuntimeError("report view is incomplete")


def create(base: str, state_path: Path, timeout_s: int) -> dict[str, Any]:
    guest = request("POST", endpoint(base, "/v1/guest-sessions"))
    token = guest["guest_token"]
    image = handwriting_png()
    ticket = request("POST", endpoint(base, "/v1/uploads"), token=token, payload={"media_type":"image/png"})
    request("PUT", urllib.parse.urljoin(base.rstrip("/") + "/", ticket["url"]), data=image)
    capture = request(
        "POST", endpoint(base, f"/v1/uploads/{ticket['upload_id']}/complete"), token=token,
        payload={"sha256":hashlib.sha256(image).hexdigest()},
    )
    request(
        "POST", endpoint(base, "/v1/me/permissions"), token=token,
        payload={"purpose_id":"service_processing","scope_kind":"SPECIMEN","scope_ref":capture["capture_id"],
                 "decision":"GRANT","notice_version":NOTICE,"request_id":f"rollback-{uuid.uuid4().hex}"},
    )
    run = request("POST", endpoint(base, "/v1/analyses"), token=token, payload={"capture_id":capture["capture_id"]})
    deadline = time.monotonic() + timeout_s
    status = None
    while time.monotonic() < deadline:
        status = request("GET", endpoint(base, f"/v1/analyses/{run['run_id']}"), token=token)
        if status["state"] == "SUCCEEDED":
            break
        if status["state"] in {"FAILED","CANCELLED"}:
            raise RuntimeError(f"analysis ended in {status['state']}: {status.get('error_code')}")
        time.sleep(1)
    else:
        raise RuntimeError(f"analysis did not finish within {timeout_s}s; last={status}")
    report_id = status["report_id"]
    view = request("GET", endpoint(base, f"/v1/reports/{report_id}?projection=OWNER"), token=token)
    verify_view(view, report_id)
    state_path.write_text(json.dumps({"token":token,"report_id":report_id}), encoding="utf-8")
    os.chmod(state_path, 0o600)
    return {"report_id":report_id,"facts":len(view["facts"]),"sections":len(view["sections"])}


def read(base: str, state_path: Path) -> dict[str, Any]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    view = request("GET", endpoint(base, f"/v1/reports/{state['report_id']}?projection=OWNER"), token=state["token"])
    verify_view(view, state["report_id"])
    return {"report_id":state["report_id"],"facts":len(view["facts"]),"sections":len(view["sections"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create","read"))
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--timeout-s", type=int, default=120)
    args = parser.parse_args(argv)
    result = create(args.base_url, args.state, args.timeout_s) if args.action == "create" else read(args.base_url, args.state)
    print(json.dumps({"result":"PASS",**result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
