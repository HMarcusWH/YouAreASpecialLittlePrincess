"""Bounded iterative maximum-cardinality IoU matching; synthetic boxes only."""
from __future__ import annotations

import json
import random
from functools import lru_cache
from hashlib import sha256

import cv2
import numpy as np
import pytest

from evaluation.segmentation import benchmark
from princess_graphology.models import Box


def _oracle(refs, boxes, threshold):
    graph = [[j for j, box in enumerate(boxes) if benchmark.iou(ref, box) >= threshold]
             for ref in refs]

    @lru_cache(None)
    def visit(i, used):
        if i == len(graph):
            return 0
        best = visit(i + 1, used)
        for j in graph[i]:
            if not (used >> j) & 1:
                best = max(best, 1 + visit(i + 1, used | (1 << j)))
        return best

    return visit(0, 0)


@pytest.mark.parametrize("threshold", (0.3, 0.5, 0.75, 1.0))
def test_small_graphs_equal_bruteforce_maximum_cardinality(threshold):
    rng = random.Random(915)
    for _ in range(180):
        count_a = rng.randrange(0, 7)
        count_b = rng.randrange(0, 7)
        def boxes(n):
            return [Box(rng.randrange(0, 15), rng.randrange(0, 15),
                        rng.randrange(1, 15), rng.randrange(1, 15))
                    for _ in range(n)]
        left, right = boxes(count_a), boxes(count_b)
        expected = _oracle(left, right, threshold)
        result = benchmark.match(left, right, threshold=threshold)
        assert result["tp"] == expected
        assert result["fp"] == count_b - expected
        assert result["fn"] == count_a - expected


def test_dense_thousand_boxes_no_recursion():
    box = Box(12, 14, 80, 20)
    result = benchmark.match([box] * 1000, [box] * 1000)
    assert (result["tp"], result["fp"], result["fn"]) == (1000, 0, 0)
    assert result["f1"] == result["mean_iou"] == 1.0


def test_sparse_four_thousand_ninety_six_boxes():
    boxes = [Box(i * 7, 20, 4, 10) for i in range(4096)]
    result = benchmark.match(boxes, boxes)
    assert result["tp"] == 4096 and result["fp"] == result["fn"] == 0
    assert result["mean_iou"] == 1.0


def test_extreme_dense_four_thousand_fails_closed():
    a = Box(1, 1, 80, 80)
    with pytest.raises(ValueError, match="^matching_complexity_exceeded$"):
        benchmark.match([a] * 4096, [a] * 4096)


def test_large_direct_inputs_are_refused_before_graph_allocation():
    a = Box(1, 1, 80, 80)
    for left, right in (([a] * 4097, [a]), ([a], [a] * 4097)):
        with pytest.raises(ValueError, match="^matching_complexity_exceeded$"):
            benchmark.match(left, right)


def test_matcher_budget_spans_multiple_calls_and_never_returns_partial_metrics():
    a = Box(1, 1, 80, 80)
    first_cost = 3  # 1 x-candidate + 1 BFS visit + 1 augment visit
    budget = benchmark._MatchingBudget(first_cost)
    result = benchmark.match([a], [a], budget=budget)
    assert result["tp"] == 1 and budget.remaining == 0
    with pytest.raises(ValueError, match="^matching_complexity_exceeded$"):
        benchmark.match([a], [a], budget=budget)


def test_threshold_boundary_and_tie_pairing_are_deterministic():
    left = [Box(0, 0, 10, 10)]
    half_iou = Box(0, 0, 5, 10)   # exactly 0.5 IoU
    assert benchmark.match(left, [half_iou], threshold=0.5)["tp"] == 1
    assert benchmark.match(left, [half_iou], threshold=0.500001)["tp"] == 0
    paired = benchmark.match(left, [left[0], left[0]])
    assert paired["tp"] == 1 and paired["precision"] == 0.5
    assert paired["mean_iou"] == 1 and paired["mean_center_error_px"] == 0


def test_secondary_metrics_and_method_are_versioned():
    assert benchmark.MATCHER_METHOD == "iou-maxcard-hk/1"
    ref = Box(10, 20, 40, 20)
    right = [Box(10, 20, 40, 20), Box(20, 20, 40, 20)]
    results = [benchmark.match([ref], right) for _ in range(5)]
    assert results == [results[0]] * 5
    assert results[0]["tp"] == 1
    assert results[0]["mean_iou"] == 1.0
    assert results[0]["mean_center_error_px"] == 0.0


def test_missing_annotations_and_explicit_empty_remain_distinct():
    a = Box(0, 0, 10, 10)
    assert benchmark.match([], [])["f1"] == 1
    assert benchmark.match([], [a])["f1"] == 0
    assert benchmark.match([a], [])["f1"] == 0
    row = {"specimen_id": "synthetic", "writer_group": "writer-0",
           "capture_group": "capture-0", "image_path": "x.png",
           "sha256": "f" * 64, "paper": "blank"}
    assert benchmark.validate_record(row, "synthetic") == (None, None)
    assert benchmark.validate_record({**row, "lines": [], "words": []}, "synthetic") == ((), ())


def test_manifest_budget_is_shared_across_specimens(tmp_path, monkeypatch):
    image = np.full((100, 250, 3), 255, dtype=np.uint8)
    raw = cv2.imencode(".png", image)[1].tobytes()
    root = tmp_path / "inputs"
    root.mkdir()
    (root / "a.png").write_bytes(raw)
    (root / "b.png").write_bytes(raw)
    data = []
    for idx, name in enumerate(("a.png", "b.png")):
        data.append({"specimen_id": "specimen-" + str(idx), "writer_group": "writer-" + str(idx),
                     "capture_group": "capture-" + str(idx), "paper": "blank",
                     "image_path": name, "sha256": sha256(raw).hexdigest(), "lines": [], "words": []})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 2, "split": "synthetic",
                                    "synthetic": True, "annotation_frame": "original_image",
                                    "specimens": data}))
    original_evaluate = benchmark.evaluate
    box = Box(3, 3, 30, 10)
    seen = []
    def budgeted_evaluate(*args, matching_budget=None, **kwargs):
        seen.append(matching_budget)
        benchmark.match([box], [box], budget=matching_budget)
        return original_evaluate(*args, matching_budget=matching_budget, **kwargs)
    monkeypatch.setattr(benchmark, "evaluate", budgeted_evaluate)
    monkeypatch.setattr(benchmark, "MAX_RUN_MATCH_WORK", 5)
    with pytest.raises(ValueError, match="^matching_complexity_exceeded$"):
        benchmark.run_manifest(manifest, root, profile="legacy")
    assert len(seen) == 2 and seen[0] is seen[1]


def test_graph_complexity_exception_is_not_a_pass_result():
    budget = benchmark._MatchingBudget(0)
    box = Box(0, 0, 30, 10)
    with pytest.raises(ValueError, match="^matching_complexity_exceeded$"):
        benchmark.match([box], [box], budget=budget)
