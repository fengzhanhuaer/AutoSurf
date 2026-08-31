from __future__ import annotations

import re
from functools import lru_cache
from typing import Any


NEXUSPHP_CAPTCHA_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


def recognize_nexusphp_captcha(image: bytes) -> str | None:
    candidates: list[bytes] = []
    for prepare in (
        preprocess_nexusphp_captcha,
        lambda payload: preprocess_nexusphp_captcha_grayscale(payload, 80),
        lambda payload: preprocess_nexusphp_captcha_grayscale(payload, 160),
    ):
        try:
            candidates.append(prepare(image))
        except Exception:
            continue

    recognized: list[str] = []
    try:
        engine = _ocr_engine()
    except Exception:
        return None
    for candidate in candidates:
        try:
            value = str(engine.classification(candidate) or "").strip().upper()
        except Exception:
            continue
        if NEXUSPHP_CAPTCHA_PATTERN.fullmatch(value):
            recognized.append(value)
    if not recognized:
        return None

    counts = {value: recognized.count(value) for value in set(recognized)}
    best = max(counts, key=lambda value: counts[value])
    if len(counts) == 1 or counts[best] >= 2:
        return best
    return None


def preprocess_nexusphp_captcha(image: bytes) -> bytes:
    if not image or len(image) > 1_000_000:
        raise ValueError("invalid captcha image")

    import cv2
    import numpy as np

    source = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if source is None or source.shape[0] < 8 or source.shape[1] < 8:
        raise ValueError("invalid captcha image")

    source = source[2:-2, 2:-2]
    dark = np.max(cv2.cvtColor(source, cv2.COLOR_BGR2RGB), axis=2) < 40
    component_mask = dark.astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(component_mask, connectivity=8)
    retained = np.zeros(component_mask.shape, dtype=bool)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= 2:
            retained |= labels == label
    if not retained.any():
        raise ValueError("captcha contains no dark characters")

    rows, columns = np.where(retained)
    padding = 3
    top = max(int(rows.min()) - padding, 0)
    bottom = min(int(rows.max()) + padding + 1, retained.shape[0])
    left = max(int(columns.min()) - padding, 0)
    right = min(int(columns.max()) + padding + 1, retained.shape[1])
    cropped = retained[top:bottom, left:right]
    prepared = np.full(cropped.shape, 255, dtype=np.uint8)
    prepared[cropped] = 0
    encoded, payload = cv2.imencode(".png", prepared)
    if not encoded:
        raise ValueError("captcha preprocessing failed")
    return payload.tobytes()


def preprocess_nexusphp_captcha_grayscale(image: bytes, threshold: int) -> bytes:
    if not image or len(image) > 1_000_000:
        raise ValueError("invalid captcha image")

    import cv2
    import numpy as np

    source = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if source is None or source.shape[0] < 8 or source.shape[1] < 8:
        raise ValueError("invalid captcha image")

    gray = cv2.cvtColor(source[2:-2, 2:-2], cv2.COLOR_BGR2GRAY)
    _, prepared = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    encoded, payload = cv2.imencode(".png", prepared)
    if not encoded:
        raise ValueError("captcha preprocessing failed")
    return payload.tobytes()


@lru_cache(maxsize=1)
def _ocr_engine() -> Any:
    import ddddocr

    return ddddocr.DdddOcr(show_ad=False)
