import cv2
import numpy as np
import pytest

from autosurf.automations import captcha_ocr


def test_nexusphp_captcha_preprocessing_removes_colored_noise():
    source = np.full((40, 150, 3), 255, dtype=np.uint8)
    source[8:20, 12:20] = (0, 0, 0)
    source[20:32, 22:30] = (0, 0, 0)
    source[12:16, 80:84] = (255, 0, 0)
    encoded, payload = cv2.imencode(".png", source)
    assert encoded is True

    prepared = captcha_ocr.preprocess_nexusphp_captcha(payload.tobytes())
    image = cv2.imdecode(np.frombuffer(prepared, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)

    assert image is not None
    assert set(np.unique(image)).issubset({0, 255})
    assert np.count_nonzero(image == 0) == 192


@pytest.mark.parametrize(
    ("classified", "expected"),
    [
        ("mep5mp", "MEP5MP"),
        ("MEP5M", None),
        ("MEP5MP7", None),
        ("MEP-MP", None),
        ("", None),
    ],
)
def test_nexusphp_captcha_requires_exactly_six_alphanumeric_characters(
    monkeypatch, classified, expected,
):
    class Engine:
        def classification(self, image):
            assert image == b"prepared"
            return classified

    monkeypatch.setattr(captcha_ocr, "preprocess_nexusphp_captcha", lambda _image: b"prepared")
    monkeypatch.setattr(captcha_ocr, "_ocr_engine", lambda: Engine())

    assert captcha_ocr.recognize_nexusphp_captcha(b"source") == expected
