"""Small, stdlib-only building blocks shared by consent contract boundaries.

These prevent accidental mutation and ambiguous indexing. They are not a sandbox
against hostile Python code, and an unkeyed digest is not approver authentication.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Issue:
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.where}: {self.message}"


@dataclass(frozen=True)
class ValidationResult(Generic[T]):
    value: T | None
    issues: tuple[Issue, ...] = ()

    def __post_init__(self) -> None:
        if (self.value is None) != bool(self.issues):
            raise ValueError("a validation result has either a value or issues, never both/neither")


def _immutable(*_args, **_kwargs):
    raise TypeError("validated contract snapshots are immutable")


class FrozenDict(dict):
    __slots__ = ()
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


class FrozenList(list):
    __slots__ = ()
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return self


def freeze_json(value):
    """Copy then recursively freeze an already validated JSON tree."""
    if isinstance(value, dict):
        return FrozenDict((key, freeze_json(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return FrozenList(freeze_json(item) for item in value)
    return value


def input_tree_issues(value, where: str, *, max_nodes: int = 2_000_000, max_depth: int = 48, max_text_chars: int = 32_000_000) -> list[Issue]:
    """Bound shape traversal before recursive JSON/schema routines touch caller input.

    Only plain JSON values are accepted at a public raw-input boundary. Aliased
    Python containers are rejected too: JSON cannot express aliases or cycles.
    """
    stack = [(value, 0)]
    containers: set[int] = set()
    count = text_chars = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > max_nodes or depth > max_depth:
            return [Issue("INPUT_LIMIT", where, "contract exceeds the node/depth budget")]
        if type(item) in (dict, list) or isinstance(item, (FrozenDict, FrozenList)):
            if id(item) in containers:
                return [Issue("NON_JSON_INPUT", where, "aliased or cyclic containers are not JSON")]
            containers.add(id(item))
            if isinstance(item, dict):
                text_chars += sum(len(key) for key in item if isinstance(key, str))
                if any(type(key) is not str for key in item):
                    return [Issue("NON_JSON_INPUT", where, "object keys must be strings")]
                stack.extend((child, depth + 1) for child in item.values())
            else:
                stack.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, int, float, bool, type(None)):
            return [Issue("NON_JSON_INPUT", where, f"unsupported value type {type(item).__name__}")]
        elif type(item) is str:
            text_chars += len(item)
        elif type(item) is float and not math.isfinite(item):
            return [Issue("NON_JSON_INPUT", where, "non-finite number")]
        if text_chars > max_text_chars:
            return [Issue("INPUT_LIMIT", where, "contract exceeds the text budget")]
    return []


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def unique_index(rows, key, *, code: str, where: str) -> ValidationResult[dict]:
    """Never return an index when any canonical identity is ambiguous."""
    result, repeated = {}, set()
    for row in rows:
        identity = key(row)
        if identity in result:
            repeated.add(identity)
        else:
            result[identity] = row
    if repeated:
        return ValidationResult(None, tuple(
            Issue(code, where, f"duplicate canonical identity {identity!r}")
            for identity in sorted(repeated, key=repr)
        ))
    return ValidationResult(result)


def rooted_nodes(parents: dict[str, str | None], excluded: set[str]) -> set[str]:
    """Iterative O(V+E) ancestry with cycle, missing-parent and invalidity propagation."""
    verdict = {node: False for node in excluded}
    for origin in parents:
        if origin in verdict:
            continue
        trail, seen = [], set()
        node = origin
        while node is not None and node not in verdict and node not in seen:
            if node not in parents:
                verdict[node] = False
                break
            seen.add(node)
            trail.append(node)
            node = parents[node]
        valid = node is None or (node not in seen and verdict.get(node, False))
        for ancestor in trail:
            verdict[ancestor] = valid
    return {node for node in parents if verdict.get(node, False)}
