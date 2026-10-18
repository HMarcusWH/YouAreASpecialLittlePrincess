"""Synthetic-only predecode limits and evaluator/worker pixel parity."""
from __future__ import annotations

import io
import json
import struct
import zlib
from hashlib import sha256

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from evaluation.segmentation import benchmark
from princess_app.adapters.imaging import decode_image
from princess_app.domain.intake import MAX_DECODED_PIXELS
from princess_graphology.context import prepare_context


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _solid_gray_png(width: int, height: int, value: int = 245) -> bytes:
    """Valid compressed PNG without allocating its entire decoded pixel raster."""
    scanline = b"\x00" + bytes((value,)) * width
    compressor = zlib.compressobj(level=6)
    compressed = bytearray()
    for _ in range(height):
        compressed.extend(compressor.compress(scanline))
    compressed.extend(compressor.flush())
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", bytes(compressed)) + _chunk(b"IEND", b""))


def _manifest(tmp_path, raw: bytes, *, include_annotations=True, digest=None):
    image_root = tmp_path / "images"
    image_root.mkdir(exist_ok=True)
    (image_root / "sample.bin").write_bytes(raw)
    row = {"specimen_id": "synthetic-budget-test", "writer_group": "synthetic-writer",
           "capture_group": "synthetic-capture", "image_path": "sample.bin",
           "sha256": digest or sha256(raw).hexdigest(), "paper": "blank"}
    if include_annotations:
        row.update(lines=[], words=[])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 2, "split": "synthetic",
                                    "annotation_frame": "original_image",
                                    "synthetic": True, "specimens": [row]}))
    return manifest, image_root


def _forbid_native_decode(monkeypatch):
    def fail(*_args, **_kwargs):
        pytest.fail("cv2.imdecode was called before the image was admitted")
    monkeypatch.setattr(benchmark.cv2, "imdecode", fail)


def test_compressed_25_million_pixel_png_never_reaches_native_decoder(tmp_path, monkeypatch):
    raw = _solid_gray_png(5000, 5000)
    assert len(raw) < 200_000  # compressed size is not a decoded-memory bound
    manifest, root = _manifest(tmp_path, raw)
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="benchmark image header rejected"):
        benchmark.run_manifest(manifest, root, profile="legacy")


def test_exact_boundary_is_admissible_without_decoding():
    raw = _solid_gray_png(6000, 4000)
    header = benchmark._checked_benchmark_image_header(raw)
    assert (header.width, header.height) == (6000, 4000)
    assert header.width * header.height == MAX_DECODED_PIXELS == benchmark.MAX_PIXELS


@pytest.mark.parametrize("width,height", ((31, 90), (12001, 40), (4000, 6001)))
def test_invalid_dimensions_fail_before_native_decoder(tmp_path, monkeypatch, width, height):
    raw = _solid_gray_png(width, height)
    manifest, root = _manifest(tmp_path, raw)
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="benchmark image header rejected"):
        benchmark.run_manifest(manifest, root)


def test_invalid_digest_never_reaches_header_or_decoder(tmp_path, monkeypatch):
    raw = _solid_gray_png(240, 100)
    manifest, root = _manifest(tmp_path, raw, digest="0" * 64)
    def fail(*_args, **_kwargs):
        pytest.fail("header was inspected before the image digest")
    monkeypatch.setattr(benchmark, "inspect_header", fail)
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="image SHA256 mismatch"):
        benchmark.run_manifest(manifest, root)


@pytest.mark.parametrize("bad", (b"not an image", b"\x89PNG\r\n\x1a\n", b"GIF89a" + b"\x00" * 40,
                                  b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 40))
def test_malformed_or_unapproved_formats_rejected_before_native_decode(tmp_path, monkeypatch, bad):
    manifest, root = _manifest(tmp_path, bad)
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="benchmark image header rejected"):
        benchmark.run_manifest(manifest, root)


def test_multiframe_png_refused_before_native_decode(tmp_path, monkeypatch):
    first = Image.new("RGB", (240, 100), "white")
    second = Image.new("RGB", (240, 100), "black")
    output = io.BytesIO()
    first.save(output, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
    manifest, root = _manifest(tmp_path, output.getvalue())
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="benchmark image header rejected"):
        benchmark.run_manifest(manifest, root)


@pytest.mark.parametrize("orientation", range(2, 9))
def test_exif_oriented_jpeg_refused_before_native_decode(tmp_path, monkeypatch, orientation):
    image = Image.new("RGB", (240, 100), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    manifest, root = _manifest(tmp_path, output.getvalue())
    _forbid_native_decode(monkeypatch)
    with pytest.raises(ValueError, match="EXIF orientation"):
        benchmark.run_manifest(manifest, root)


@pytest.mark.parametrize("fault", ("missing", "wrong_dimensions", "sixteen_bit", "bad_channels"))
def test_native_decoder_output_still_requires_contract(tmp_path, monkeypatch, fault):
    raw = _solid_gray_png(240, 100)
    manifest, root = _manifest(tmp_path, raw)
    bad_outputs = {
        "missing": None,
        "wrong_dimensions": np.zeros((101, 240), dtype=np.uint8),
        "sixteen_bit": np.zeros((100, 240), dtype=np.uint16),
        "bad_channels": np.zeros((100, 240, 2), dtype=np.uint8),
    }
    monkeypatch.setattr(benchmark.cv2, "imdecode", lambda *_a, **_kw: bad_outputs[fault])
    with pytest.raises(ValueError, match="undecodable|unsupported decoded|dimensions disagree"):
        benchmark.run_manifest(manifest, root)


def test_unannotated_means_unknown_not_empty():
    row = {"specimen_id": "x", "writer_group": "writer", "capture_group": "capture",
           "image_path": "sample", "sha256": "a" * 64, "paper": "blank"}
    assert benchmark.validate_record(row, "synthetic") == (None, None)
    assert benchmark.validate_record({**row, "lines": [], "words": []}, "synthetic") == ((), ())


def test_normal_four_thousand_by_three_thousand_png_run_manifest(tmp_path):
    manifest, root = _manifest(tmp_path, _solid_gray_png(4000, 3000))
    result = benchmark.run_manifest(manifest, root, profile="legacy")
    assert result["data_origin"] == "SYNTHETIC_FIXTURE"
    assert result["summary"]["overall"]["count"] == 1


def _sample_bytes(fmt: str) -> tuple[bytes, str]:
    """High-contrast synthetic ink avoids decoder-dependent JPEG edge ambiguity."""
    im = Image.new("RGB", (280, 140), "white")
    draw = ImageDraw.Draw(im)
    draw.rectangle((20, 50, 110, 57), fill="black")
    draw.rectangle((145, 55, 255, 62), fill="black")
    if fmt == "rgba_png":
        im = im.convert("RGBA")
        im.putpixel((5, 5), (0, 0, 0, 0))
        im.putpixel((6, 6), (0, 0, 0, 128))
    if fmt == "gray_png":
        im = im.convert("L")
    kind = "JPEG" if fmt == "jpeg" else "PNG"
    output = io.BytesIO()
    im.save(output, format=kind, quality=95)
    return output.getvalue(), ("image/jpeg" if kind == "JPEG" else "image/png")


@pytest.mark.parametrize("fmt", ("gray_png", "rgb_png", "rgba_png", "jpeg"))
def test_benchmark_and_worker_agree_on_unoriented_image_geometry(fmt, tmp_path):
    raw, media_type = _sample_bytes(fmt)
    manifest, root = _manifest(tmp_path, raw)
    result = benchmark.run_manifest(manifest, root, profile="legacy")
    assert result["data_origin"] == "SYNTHETIC_FIXTURE"
    header = benchmark._checked_benchmark_image_header(raw)
    worker = decode_image(raw, media_type)
    native = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    native_context = prepare_context(native, grid_profile="legacy", deskew_enabled=False)
    worker_context = prepare_context(worker.pixels, grid_profile="legacy", deskew_enabled=False)
    assert worker.header == header
    assert native_context.gray.shape == worker_context.gray.shape
    assert np.array_equal(native_context.mask, worker_context.mask)
    assert native_context.lines == worker_context.lines
    assert native_context.words == worker_context.words
