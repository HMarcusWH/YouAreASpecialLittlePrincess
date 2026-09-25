from __future__ import annotations
import cv2
import numpy as np
from .models import AnalysisResult, Region, Measurement
from .preprocessing.geometry import deskew
from .preprocessing.binarize import binarize
from .preprocessing.denoise import denoise
from .segmentation import segment_lines, detect_words, filter_word_proposals
from .features import measure_layout, measure_baseline, measure_spacing, measure_slant, measure_ink

class GraphologyEngine:
    """Deterministic static-image measurement engine. Personality inference is downstream."""

    def __init__(self, max_dimension=2200):
        self.max_dimension = max_dimension

    def analyze_file(self, path):
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(path)
        return self.analyze(image, source=path)

    def analyze(self, image, source="<array>"):
        gray = image.copy() if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        scale = min(1.0, self.max_dimension / max(h, w))
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        corrected, applied = deskew(gray)
        binary_result = binarize(corrected, method="auto")
        mask = binary_result.mask
        denoised = denoise(mask, speckle=True, large_blobs=True, closing=False)
        cleaned = denoised[0] if isinstance(denoised, tuple) else denoised

        lines = segment_lines(cleaned)
        proposals = filter_word_proposals(detect_words(corrected), cleaned.shape)
        words = [proposal.box for proposal in proposals]

        height, width = cleaned.shape
        result = AnalysisResult(source=source, width=width, height=height)
        result.metadata.update({
            "deskew_applied_deg": float(applied),
            "binarize_method": getattr(binary_result, "method", "auto"),
        })

        result.regions.extend(Region(f"line_{i}", "LINE", box) for i, box in enumerate(lines))
        result.regions.extend(Region(f"word_{i}", "WORD", box) for i, box in enumerate(words))

        measurements = (
            measure_layout(cleaned, lines, words)
            + measure_baseline(cleaned, lines)
            + measure_spacing(lines, words)
            + measure_slant(cleaned)
            + measure_ink(corrected, cleaned)
        )
        for measurement in measurements:
            result.add(measurement)

        result.add(Measurement("DESKEW_ANGLE", float(applied), "degrees", method_version="projection_hough_v1"))
        result.add(Measurement("IMAGE_WIDTH_PX", width, "pixels", method_version="image_meta_v1"))
        result.add(Measurement("IMAGE_HEIGHT_PX", height, "pixels", method_version="image_meta_v1"))
        return result
