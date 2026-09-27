"""Upload policy and content sniffing (T04). Pure: no decoding, no I/O.

Starting limits come from docs/roadmap/05-release-operations.md and are
engineering settings to benchmark, not proof of safety. JPEG and PNG are the
only accepted formats until an audited conversion path exists; phones
convert HEIC to JPEG before upload. A declared media type must match the
bytes (never trust client MIME or extension).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ports.base import InvalidInput

INTAKE_POLICY_VERSION = "intake-policy/1"
ALLOWED_MEDIA = frozenset({"image/jpeg", "image/png"})
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_DECODED_PIXELS = 24_000_000
MAX_DIMENSION = 12_000
MIN_DIMENSION = 32
UPLOAD_TICKET_SECONDS = 900
UPLOADS_PER_DAY = 20
UPLOADS_PER_DAY_WITHOUT_CHALLENGE = 3
MAX_ACTIVE_JOBS = 3

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avif")


def sniff_media_type(data: bytes) -> str:
    """Identify the container from magic bytes; reject everything unsupported."""
    head = bytes(data[:32])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        raise InvalidInput("unsupported_media_heif")
    if head.startswith((b"GIF87a", b"GIF89a")):
        raise InvalidInput("unsupported_media_gif")
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        raise InvalidInput("unsupported_media_webp")
    raise InvalidInput("unsupported_media")


@dataclass(frozen=True)
class ImageHeader:
    media_type: str
    width: int
    height: int
    frames: int
    exif_orientation: int

    @property
    def oriented_size(self) -> tuple[int, int]:
        return (self.height, self.width) if self.exif_orientation in (5, 6, 7, 8) else (self.width, self.height)


def check_header(header: ImageHeader, declared_media_type: str) -> None:
    if header.media_type != declared_media_type:
        raise InvalidInput("media_type_mismatch")
    if header.frames != 1:
        raise InvalidInput("animated_or_multi_frame_image")
    if not (MIN_DIMENSION <= header.width <= MAX_DIMENSION and MIN_DIMENSION <= header.height <= MAX_DIMENSION):
        raise InvalidInput("image_dimensions_out_of_range")
    if header.width * header.height > MAX_DECODED_PIXELS:
        raise InvalidInput("image_too_many_pixels")
    if header.exif_orientation not in range(1, 9):
        raise InvalidInput("invalid_orientation")
