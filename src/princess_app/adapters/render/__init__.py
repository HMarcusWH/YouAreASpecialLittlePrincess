"""Sandboxed renderer process (the ``render_worker`` boundary, T21).

Runs ``apps/render`` (Node + offline Chromium) as a child process. The child
gets the authorized projection on stdin and nothing else: an environment with
only ``PATH``, ``HOME`` and the Chromium path, no database URL, storage key,
model key or session secret, and a browser with JavaScript disabled and every
network request aborted. It writes PDF/PNG bytes to stdout and a single error
code to stderr.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...ports.base import InvalidInput, PermanentFailure, TransientUnavailable

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BUNDLE = ROOT / "apps" / "render" / "dist" / "render.mjs"
_CODE = re.compile(r"^[a-z_]{1,64}$")
MAX_STDOUT = 10 * 1024 * 1024 + 1


class SubprocessRenderer:
    def __init__(self, command: Sequence[str] | None = None, *, timeout_s: float = 60.0,
                 chromium: str | None = None) -> None:
        self.command = list(command or ["node", str(DEFAULT_BUNDLE)])
        self.timeout_s = timeout_s
        # Runtime images provide an explicitly qualified Chromium path. Tests
        # and callers may still override it; local development falls back to
        # Playwright's ordinary executable discovery when neither is present.
        self.chromium = chromium if chromium is not None else os.environ.get("PRINCESS_CHROMIUM")

    def _env(self) -> dict[str, str]:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp")}
        if self.chromium:
            env["PRINCESS_CHROMIUM"] = self.chromium
        return env

    def render(self, view: Mapping[str, Any], layout: str, locale: str, generated_at: str) -> bytes:
        payload = json.dumps({"view": view, "layout": layout, "locale": locale, "generated_at": generated_at},
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
        try:
            done = subprocess.run(self.command, input=payload, capture_output=True, timeout=self.timeout_s,
                                  env=self._env(), cwd=str(ROOT), check=False)
        except subprocess.TimeoutExpired:
            raise TransientUnavailable("render_timeout") from None
        except OSError:
            raise TransientUnavailable("renderer_unavailable") from None
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        code = lines[-1].strip() if lines else ""
        code = code if _CODE.match(code) else "render_failed"
        if done.returncode == 2:
            raise InvalidInput(code)
        if done.returncode != 0:
            raise PermanentFailure(code)
        if len(done.stdout) >= MAX_STDOUT:
            raise PermanentFailure("render_output_size")
        return done.stdout


__all__ = ["DEFAULT_BUNDLE", "SubprocessRenderer"]
