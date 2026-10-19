"""Strict JSON decoding for frozen segmentation-evaluation evidence.

Reject duplicate object members at every depth and nonstandard numeric
constants before accepting a digest, policy, or annotation. Error text
contains no member values, specimen identifiers, or private paths.
"""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

MAX_POLICY_JSON_BYTES = 128 * 1024
MAX_MANIFEST_JSON_BYTES = 64 * 1024 * 1024
MAX_THREE_SPLIT_JSON_BYTES = 128 * 1024 * 1024


def read_bounded_json_bytes(path: Path, maximum: int) -> bytes:
    """Read one admitted regular file exactly once, without unbounded allocation.

    This supports kernel-sealed /proc/self/fd/N memfd input in trusted workers.
    Keep path/contents out of all user-visible error messages.
    """
    if type(maximum) is not int or maximum < 0:
        raise ValueError("invalid frozen JSON byte budget")
    try:
        with Path(path).open("rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
                raise ValueError("frozen JSON exceeds byte budget")
            content = stream.read(maximum + 1)
    except OSError as exc:
        raise ValueError("frozen JSON admission failed") from exc
    if len(content) > maximum:
        raise ValueError("frozen JSON exceeds byte budget")
    return content



def _unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate JSON member in frozen evidence")
        data[key] = value
    return data


def _reject_constant(_literal):
    raise ValueError("nonfinite JSON constant in frozen evidence")


def _finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("nonfinite JSON number in frozen evidence")
    return value


def strict_loads(raw: bytes | str):
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("invalid frozen JSON") from exc
