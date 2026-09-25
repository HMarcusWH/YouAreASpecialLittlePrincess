# Adapted from NitinRamchandani/ocr-preprocessing-tool (MIT). See THIRD_PARTY_NOTICES.md.
"""Character normalisation and feature extraction.

Normalisation turns a variable-size glyph crop into a fixed-size canonical
form. Feature extraction turns that form into the vector the classifier
consumes. Both are here because they are the boundary between the image
pipeline and the recogniser, and both must be byte-for-byte identical at
training and inference time. Any drift between the two is a silent accuracy
loss that looks like a model problem and is not.
"""

from __future__ import annotations

import cv2
import numpy as np

DEFAULT_SIZE = (32, 32)


def normalize_glyph(patch: np.ndarray,
                    size: tuple[int, int] = DEFAULT_SIZE,
                    margin: int = 2,
                    centre_of_mass: bool = True) -> np.ndarray:
    """Normalise a character crop to a fixed square.

    Steps: tight-crop to the ink bounding box, scale the longer axis to fit
    inside ``size`` minus the margin while preserving aspect ratio, then place
    the result on a blank canvas.

    Aspect ratio is preserved rather than stretched. Stretching every glyph to
    a square destroys a real discriminator: a stretched '1' becomes hard to
    tell from a '7', and a stretched '.' becomes a filled block.

    When ``centre_of_mass`` is set the glyph is positioned by its ink centroid
    rather than its bounding box centre. This is the MNIST convention and it
    measurably reduces intra-class variance, because a 'j' with a long
    descender has a bounding box centre well below where a reader perceives
    the character to sit.

    Args:
        patch: binary crop, ink as 255.
        size: output ``(height, width)``.
        margin: blank border in pixels.
        centre_of_mass: centre by ink centroid instead of bounding box.

    Returns:
        ``uint8`` array of shape ``size``, ink as 255.
    """
    if patch.size == 0:
        return np.zeros(size, dtype=np.uint8)

    ink = np.argwhere(patch > 0)
    if ink.size == 0:
        return np.zeros(size, dtype=np.uint8)

    y0, x0 = ink.min(axis=0)
    y1, x1 = ink.max(axis=0)
    cropped = patch[y0:y1 + 1, x0:x1 + 1]

    target_h, target_w = size
    inner_h = max(1, target_h - 2 * margin)
    inner_w = max(1, target_w - 2 * margin)

    height, width = cropped.shape
    scale = min(inner_h / height, inner_w / width)
    new_h = max(1, int(round(height * scale)))
    new_w = max(1, int(round(width * scale)))

    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(cropped, (new_w, new_h), interpolation=interpolation)
    resized = (resized > 127).astype(np.uint8) * 255  # rebinarize after interpolation

    canvas = np.zeros(size, dtype=np.uint8)

    if centre_of_mass:
        moments = cv2.moments(resized, binaryImage=True)
        if moments["m00"] > 0:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        else:
            cx, cy = new_w / 2.0, new_h / 2.0
        top = int(round(target_h / 2.0 - cy))
        left = int(round(target_w / 2.0 - cx))
    else:
        top = (target_h - new_h) // 2
        left = (target_w - new_w) // 2

    top = int(np.clip(top, 0, target_h - new_h))
    left = int(np.clip(left, 0, target_w - new_w))
    canvas[top:top + new_h, left:left + new_w] = resized
    return canvas


# ---------------------------------------------------------------------------
# Feature extractors
# ---------------------------------------------------------------------------

def feature_raw_pixels(glyph: np.ndarray) -> np.ndarray:
    """Flattened pixel intensities, scaled to ``[0, 1]``.

    For a 32x32 glyph this is 1024 features. Simple, and a perfectly reasonable
    baseline for a shallow network, but it encodes no invariance at all: a
    one-pixel shift changes every value.
    """
    return (glyph.astype(np.float32) / 255.0).ravel()


def feature_zoning(glyph: np.ndarray, zones: tuple[int, int] = (4, 4)) -> np.ndarray:
    """Ink density per zone of a grid.

    A 4x4 grid over a 32x32 glyph gives 16 features. Coarse, cheap, and
    tolerant of small shifts and stroke-width variation, which is exactly why
    it remains a standard baseline in handwriting recognition despite being
    trivial to compute.
    """
    rows, columns = zones
    height, width = glyph.shape
    binary = (glyph > 0).astype(np.float32)

    features = np.empty(rows * columns, dtype=np.float32)
    for r in range(rows):
        for c in range(columns):
            y0 = r * height // rows
            y1 = (r + 1) * height // rows
            x0 = c * width // columns
            x1 = (c + 1) * width // columns
            cell = binary[y0:y1, x0:x1]
            features[r * columns + c] = cell.mean() if cell.size else 0.0

    return features


def feature_projection(glyph: np.ndarray) -> np.ndarray:
    """Normalised horizontal and vertical projection profiles.

    For 32x32 this is 64 features. Captures where ink sits along each axis.
    Distinguishes shapes that zoning blurs together, for instance 'E' with its
    three horizontal bars against 'F' with two.
    """
    binary = (glyph > 0).astype(np.float32)
    horizontal = binary.sum(axis=1)
    vertical = binary.sum(axis=0)

    total = binary.sum()
    if total > 0:
        horizontal = horizontal / total
        vertical = vertical / total

    return np.concatenate([horizontal, vertical]).astype(np.float32)


def feature_hu_moments(glyph: np.ndarray) -> np.ndarray:
    """Seven Hu moment invariants, log-scaled.

    Invariant to translation, scale, and rotation. Rotation invariance is a
    mixed blessing for characters: it helps with slight rotation and hurts
    because it makes '6' and '9' indistinguishable. Included as a supplement,
    never alone.

    Log scaling is necessary because the raw moments span many orders of
    magnitude. It also introduces a problem worth being explicit about: the
    higher-order invariants (5, 6, 7) are near zero for a well-formed glyph, so
    ``-log10(|tiny|)`` becomes a large number that swings wildly between two
    renderings of the same character. Left unbounded, those three features
    dominate any distance metric and actively harm discrimination.

    The output is therefore clipped to ``[-CLIP, CLIP]`` and divided by
    ``CLIP``, putting every component in ``[-1, 1]`` alongside the other
    feature blocks. Without this the Hu terms also dominate the initial
    gradient during training, which is the same reason ``mapminmax`` is applied
    on the MATLAB side.
    """
    clip = 20.0
    moments = cv2.moments((glyph > 0).astype(np.uint8), binaryImage=True)
    hu = cv2.HuMoments(moments).ravel()
    with np.errstate(divide="ignore", invalid="ignore"):
        scaled = np.where(hu != 0, -np.sign(hu) * np.log10(np.abs(hu)), 0.0)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=clip, neginf=-clip)
    return (np.clip(scaled, -clip, clip) / clip).astype(np.float32)


def feature_crossings(glyph: np.ndarray, lines: int = 8) -> np.ndarray:
    """Count ink transitions along evenly spaced scan lines.

    Cheap and surprisingly discriminative for topology: a horizontal scan
    through the middle of an 'O' crosses ink twice, through a 'C' twice, and
    through an 'E' once or three times depending on height. Gives ``2 * lines``
    features.
    """
    binary = (glyph > 0).astype(np.int32)
    height, width = binary.shape

    counts = []
    for i in range(lines):
        row = min(height - 1, (i * height) // lines + height // (2 * lines))
        counts.append(int(np.abs(np.diff(binary[row, :])).sum()))
    for i in range(lines):
        column = min(width - 1, (i * width) // lines + width // (2 * lines))
        counts.append(int(np.abs(np.diff(binary[:, column])).sum()))

    return np.array(counts, dtype=np.float32) / 10.0


def feature_profiles(glyph: np.ndarray) -> np.ndarray:
    """Distance from each edge to the first ink pixel, on all four sides.

    Describes the outline rather than the interior. For 32x32 this gives 128
    features. Distinguishes characters with similar ink density but different
    silhouettes, such as 'D' and 'O'.

    A row with no ink is encoded as the full width, meaning "never reached".
    """
    binary = glyph > 0
    height, width = binary.shape
    features: list[float] = []

    for row in range(height):
        indices = np.where(binary[row, :])[0]
        features.append(indices[0] / width if indices.size else 1.0)
        features.append((width - 1 - indices[-1]) / width if indices.size else 1.0)

    for column in range(width):
        indices = np.where(binary[:, column])[0]
        features.append(indices[0] / height if indices.size else 1.0)
        features.append((height - 1 - indices[-1]) / height if indices.size else 1.0)

    return np.array(features, dtype=np.float32)


FEATURE_EXTRACTORS = {
    "raw": feature_raw_pixels,
    "zoning": feature_zoning,
    "projection": feature_projection,
    "hu": feature_hu_moments,
    "crossings": feature_crossings,
    "profiles": feature_profiles,
}


def extract_features(glyph: np.ndarray,
                     methods: list[str] | None = None) -> np.ndarray:
    """Concatenate several feature sets into one vector.

    The default combination is ``zoning + projection + crossings + hu``, which
    is 103 features for a 32x32 glyph. Small enough to train a shallow network
    on quickly, and far more informative per dimension than 1024 raw pixels.

    Whatever is chosen here must be used identically at training and inference
    time. That is the reason this function exists rather than the extractors
    being called ad hoc from two places.
    """
    if methods is None:
        methods = ["zoning", "projection", "crossings", "hu"]

    unknown = set(methods) - set(FEATURE_EXTRACTORS)
    if unknown:
        raise ValueError(f"unknown feature method(s): {sorted(unknown)}")

    return np.concatenate([FEATURE_EXTRACTORS[m](glyph) for m in methods])


def feature_vector_length(methods: list[str] | None = None,
                          size: tuple[int, int] = DEFAULT_SIZE) -> int:
    """Length of the vector ``extract_features`` produces, without running it.

    Used to size the input layer before any data is loaded.
    """
    probe = np.zeros(size, dtype=np.uint8)
    probe[size[0] // 4:3 * size[0] // 4, size[1] // 2] = 255
    return int(extract_features(probe, methods).shape[0])
