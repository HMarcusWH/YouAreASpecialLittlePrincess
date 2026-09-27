"""Bounded image inspection and decoding with Pillow (T04 intake/worker).

Header inspection never decodes pixels, so pixel bombs are rejected before
allocation. Decoding re-checks the header, refuses truncated or animated
files, applies the EXIF orientation, drops metadata and alpha, and returns a
uint8 array in the engine's BGR/grey convention.
"""
from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ...domain.intake import MAX_DECODED_PIXELS, ImageHeader, check_header, sniff_media_type
from ...ports.base import InvalidInput

_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG"}
_ORIENTATION_TAG = 0x0112


@dataclass(frozen=True)
class DecodedImage:
    pixels: np.ndarray
    header: ImageHeader


def _open(data: bytes) -> Image.Image:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            return Image.open(io.BytesIO(data), formats=list(_FORMATS.values()))
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise InvalidInput("image_too_many_pixels") from None
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            raise InvalidInput("malformed_image") from None


def inspect_header(data: bytes) -> ImageHeader:
    media_type = sniff_media_type(data)
    image = _open(data)
    try:
        if image.format != _FORMATS[media_type]:
            raise InvalidInput("media_type_mismatch")
        try:
            orientation = int(image.getexif().get(_ORIENTATION_TAG, 1) or 1)
        except Exception:  # noqa: BLE001 - malformed EXIF is a malformed image
            raise InvalidInput("malformed_image") from None
        frames = int(getattr(image, "n_frames", 1) or 1)
        return ImageHeader(media_type, int(image.width), int(image.height), frames, orientation)
    finally:
        image.close()


def decode_image(data: bytes, declared_media_type: str) -> DecodedImage:
    header = inspect_header(data)
    check_header(header, declared_media_type)
    image = _open(data)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            previous = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = MAX_DECODED_PIXELS
            try:
                image.load()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise InvalidInput("image_too_many_pixels") from None
            except (OSError, ValueError, SyntaxError):
                raise InvalidInput("malformed_image") from None
            finally:
                Image.MAX_IMAGE_PIXELS = previous
        oriented = ImageOps.exif_transpose(image)
        if oriented.mode in ("RGBA", "LA", "P", "PA"):
            rgba = oriented.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            oriented = Image.alpha_composite(background, rgba)
        if oriented.mode in ("L", "I;16", "I", "1"):
            array = np.asarray(oriented.convert("L"), dtype=np.uint8)
        else:
            rgb = np.asarray(oriented.convert("RGB"), dtype=np.uint8)
            array = np.ascontiguousarray(rgb[:, :, ::-1])  # engine convention: BGR
        array = array.copy()
        array.flags.writeable = False
        return DecodedImage(array, header)
    finally:
        image.close()
