"""R5-F1 image adapter: decode, orient and strip source-raster metadata.

This module, not application.exports, owns PIL/numpy and image decoding.
It never authorizes a source, resolves a provider, or creates report facts.
"""
from __future__ import annotations

import hashlib
import io

import numpy as np
from PIL import Image

from princess_graphology.engine import input_pixels_sha256

from ...application.exports.assets import (
    MAX_RASTER_BYTES, MAX_SIDE, CleanSourceRaster, _encoded_chunks,
)
from ...ports.base import InvalidInput
from ..imaging import decode_image


def clean_source_raster(blob: bytes, media_type: str) -> CleanSourceRaster:
    """Return a bounded metadata-free raster from already authorized source bytes.

    The application independently verifies source SHA and current permissions
    before this adapter is called; its result is not itself authorization.
    """
    decoded = decode_image(blob, media_type)
    pixels = decoded.pixels
    original_h, original_w = pixels.shape[:2]
    pixels_sha = input_pixels_sha256(pixels)
    if pixels.ndim == 2:
        image = Image.fromarray(pixels, mode="L")
    elif pixels.ndim == 3 and pixels.shape[2] == 3:
        image = Image.fromarray(np.ascontiguousarray(pixels[:, :, ::-1]), mode="RGB")
    else:
        raise InvalidInput("render_raster_pixels_invalid")
    w, h = image.size
    if w > MAX_SIDE or h > MAX_SIDE:
        scale = min(MAX_SIDE / w, MAX_SIDE / h)
        image = image.resize(
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            Image.Resampling.LANCZOS,
        )
    # This creates new image bytes without EXIF, comments or original metadata.
    for fmt, options in (
        ("PNG", {"optimize": True}),
        ("JPEG", {"quality": 88, "subsampling": 0}),
        ("JPEG", {"quality": 78, "subsampling": 0}),
        ("JPEG", {"quality": 64}),
        ("JPEG", {"quality": 48}),
    ):
        out = io.BytesIO()
        image.save(out, format=fmt, **options)
        clean = out.getvalue()
        if 0 < len(clean) <= MAX_RASTER_BYTES:
            return CleanSourceRaster(
                "image/png" if fmt == "PNG" else "image/jpeg",
                hashlib.sha256(clean).hexdigest(), image.width, image.height,
                _encoded_chunks(clean), original_w, original_h, pixels_sha,
            )
    raise InvalidInput("render_raster_too_large")


__all__ = ["clean_source_raster"]
