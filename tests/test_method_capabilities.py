"""The executable Free surface is the resolved method graph, not marketing metadata."""
from __future__ import annotations

import socket
import sys

import numpy as np

from princess_contracts import METHOD_CAPABILITIES, free_feature_ids, free_method_ids
from princess_graphology import GraphologyEngine


def test_current_engine_emits_exactly_resolved_free_surface():
    result = GraphologyEngine().analyze(np.full((80, 120), 255, np.uint8))
    methods = set(free_method_ids())
    features = set(free_feature_ids())
    assert len(features) == 64
    assert set(result.measurements) == features
    assert all(m.method_version in methods for m in result.measurements.values())


def test_no_learned_or_provider_dependency_is_free_eligible_transitively():
    by_id = {m["method_id"]: m for m in METHOD_CAPABILITIES["methods"]}
    for method in by_id.values():
        if method["free_eligible"]:
            assert not method["requires_learned_inference"]
            assert not method["requires_external_provider"]
            assert method["runtime_component"] == "free-core"
            assert all(by_id[dep]["free_eligible"] for dep in method["dependency_closure"])


def test_free_engine_runs_with_socket_egress_denied(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("network attempted")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    result = GraphologyEngine().analyze(np.full((40, 60), 255, np.uint8))
    assert len(result.measurements) == 64
    assert not any(name.split(".", 1)[0] in {"torch", "openai", "anthropic", "transformers", "tensorflow"} for name in sys.modules)
