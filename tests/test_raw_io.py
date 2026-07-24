import tempfile
import unittest
from pathlib import Path

import numpy as np

from isp_tool.models import RawMetadata
from isp_tool.raw_io import _unpack_mipi_row, read_plain_raw


def pack_raw10(values):
    values = np.asarray(values, dtype=np.uint16).reshape(-1, 4)
    high = (values >> 2).astype(np.uint8)
    low = (
        (values[:, 0] & 3)
        | ((values[:, 1] & 3) << 2)
        | ((values[:, 2] & 3) << 4)
        | ((values[:, 3] & 3) << 6)
    ).astype(np.uint8)
    return np.column_stack([high, low]).reshape(-1)


def pack_raw12(values):
    values = np.asarray(values, dtype=np.uint16).reshape(-1, 2)
    high = (values >> 4).astype(np.uint8)
    low = ((values[:, 0] & 15) | ((values[:, 1] & 15) << 4)).astype(np.uint8)
    return np.column_stack([high, low]).reshape(-1)


def pack_raw14(values):
    values = np.asarray(values, dtype=np.uint32).reshape(-1, 4)
    high = (values >> 6).astype(np.uint8)
    packed = (
        (values[:, 0] & 0x3F)
        | ((values[:, 1] & 0x3F) << 6)
        | ((values[:, 2] & 0x3F) << 12)
        | ((values[:, 3] & 0x3F) << 18)
    )
    low = np.column_stack([
        (packed & 0xFF).astype(np.uint8),
        ((packed >> 8) & 0xFF).astype(np.uint8),
        ((packed >> 16) & 0xFF).astype(np.uint8),
    ])
    return np.column_stack([high, low]).reshape(-1)


class RawIOTests(unittest.TestCase):
    def test_mipi_unpackers(self):
        cases = [
            (10, np.array([0, 1, 511, 1023, 17, 333, 700, 999]), pack_raw10),
            (12, np.array([0, 1, 2047, 4095, 17, 333, 700, 999]), pack_raw12),
            (14, np.array([0, 1, 8191, 16383, 17, 333, 700, 999]), pack_raw14),
        ]
        for bits, values, packer in cases:
            with self.subTest(bits=bits):
                packed = packer(values)
                decoded = _unpack_mipi_row(packed, len(values), bits)
                np.testing.assert_array_equal(decoded, values)

    def test_uint16_stride_and_offset(self):
        values = np.arange(12, dtype="<u2").reshape(3, 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.raw"
            with path.open("wb") as stream:
                stream.write(b"HEAD")
                for row in values:
                    stream.write(row.tobytes())
                    stream.write(b"PAD!")
            metadata = RawMetadata(
                width=4,
                height=3,
                bit_depth=12,
                storage="uint16_le",
                row_stride_bytes=12,
                offset_bytes=4,
                black_level=[0.0] * 4,
                white_level=4095.0,
            )
            loaded = read_plain_raw(path, metadata)
            np.testing.assert_array_equal(loaded.image, values)


if __name__ == "__main__":
    unittest.main()

