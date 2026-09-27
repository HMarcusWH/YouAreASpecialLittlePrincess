"""Orchestration only: prepare shared primitives, run stages, validate results."""
from __future__ import annotations

import os

import cv2

from .context import prepare_context
from .measurements import IMPLEMENTED_FEATURE_IDS, MEASUREMENT_STAGES, STAGE_FEATURE_IDS
from .models import AnalysisResult, Box, Region
from .schema_validation import load_contract, validate_result


class GraphologyEngine:
    """Deterministic static-image descriptors; no personality or pressure inference."""

    def __init__(self, max_dimension=2200, *, deskew_enabled=True):
        if type(max_dimension) is not int or max_dimension < 1:
            raise ValueError('max_dimension must be a positive integer')
        if type(deskew_enabled) is not bool:
            raise ValueError('deskew_enabled must be boolean')
        self.max_dimension = max_dimension
        self.deskew_enabled = deskew_enabled

    def analyze_file(self, path):
        path = os.fspath(path)
        image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise FileNotFoundError(path)
        return self.analyze(image, source=path)

    def analyze(self, image, source='<array>'):
        return self._analyze(image, source)[1]

    def analyze_with_evidence(self, image, source='<array>'):
        """Return ``(AnalysisResult, evidence payload)`` from one shared context.

        The aggregate result is identical to :meth:`analyze`; the evidence payload
        is a separate versioned artifact (see :mod:`princess_graphology.evidence`).
        """
        from .evidence import collect_evidence

        ctx, result = self._analyze(image, source)
        return result, collect_evidence(ctx, result)

    def _analyze(self, image, source):
        if not isinstance(source, str):
            raise ValueError('source must be a string')
        ctx = prepare_context(image, max_dimension=self.max_dimension, deskew_enabled=self.deskew_enabled)
        contract = load_contract()
        result = AnalysisResult(source=source, width=ctx.width, height=ctx.height)
        result.metadata.update(ctx.metadata)
        result.metadata.update({'schema_version': contract['schema_version'],
                                'schema_source_sha256': contract['source_sha256'],
                                'defined_feature_count': contract['feature_count'],
                                'implemented_feature_count': len(IMPLEMENTED_FEATURE_IDS),
                                'empirically_validated_feature_count': 0,
                                'confidence_policy': 'null means uncalibrated, not zero confidence'})
        result.regions.append(Region('page_0', 'PAGE', Box(0, 0, ctx.width, ctx.height)))
        result.regions.extend(Region(f'line_{i}', 'LINE', box, 'page_0') for i, box in enumerate(ctx.lines))
        result.regions.extend(Region(f'word_{i}', 'WORD', box, f'line_{ctx.word_lines[i]}')
                              for i, box in enumerate(ctx.words))
        result.regions.extend(Region(f'component_{i}', 'COMPONENT', box, 'page_0')
                              for i, box in enumerate(ctx.components))
        if not ctx.components:
            result.warnings.append('No usable foreground detected; this is not evidence of an empty physical page.')
        if ctx.x_height_px is None:
            result.warnings.append('X-height unavailable: dependent normalized measurements are missing.')
        else:
            result.warnings.append('X-height is an experimental component-height proxy, not recognized lowercase height.')
        result.warnings.append('Segmentation, baseline, slant and thickness estimates lack corpus-level accuracy calibration.')
        for stage, expected in zip(MEASUREMENT_STAGES, STAGE_FEATURE_IDS):
            measurements = list(stage(ctx))
            if len(measurements) != len(expected) or {m.feature_id for m in measurements} != set(expected):
                raise RuntimeError(f'{stage.__name__} violated its registered feature set')
            for measurement in measurements:
                result.add(measurement)
        validate_result(result)
        return ctx, result
