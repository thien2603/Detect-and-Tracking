from io import BytesIO

import numpy as np
import pytest

from benchmarks.probe import read_ppm


def test_ppm_reader_preserves_pixels_and_frame_boundaries():
    rgb = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
    encoded = b"P6\n3 2\n255\n" + rgb.tobytes()
    stream = BytesIO(encoded * 2)
    for _ in range(2):
        assert np.array_equal(read_ppm(stream), rgb[:, :, ::-1])
    assert read_ppm(stream) is None


@pytest.mark.parametrize("encoded", [b"BAD\n", b"P6\n0 1\n255\n", b"P6\n1 1\n256\n"])
def test_ppm_reader_rejects_invalid_header(encoded):
    with pytest.raises(ValueError):
        read_ppm(BytesIO(encoded))


def test_ppm_reader_rejects_partial_frame():
    with pytest.raises(OSError, match="during"):
        read_ppm(BytesIO(b"P6\n3 2\n255\n\0\0"))
