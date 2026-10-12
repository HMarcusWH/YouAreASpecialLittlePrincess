"""Strict JSON decoding for frozen segmentation-evaluation evidence.

Reject duplicate object members at every depth and nonstandard numeric
constants before accepting a digest, policy, or annotation. Error text
contains no member values, specimen identifiers, or private paths.
"""
from __future__ import annotations

import json


def _unique_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate JSON member in frozen evidence")
        data[key] = value
    return data


def _reject_constant(_literal):
    raise ValueError("nonfinite JSON constant in frozen evidence")


def strict_loads(raw: bytes | str):
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid frozen JSON") from exc
