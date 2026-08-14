import tempfile
import unittest
from pathlib import Path

import numpy as np

from isp_tool.models import ISPError
from isp_tool.yuv import (
    YUVFrame,
    YUVMetadata,
    compute_yuv_histogram,
    frame_size_bytes,
    infer_yuv_filename,
    infer_yuv_metadata,
    normalize_yuv_sample,
    read_yuv_frame,
    validate_yuv_file,
    yuv_to_rgb,
)


class YUVFilenameInferenceTests(unittest.TestCase):
    def test_camera_style_420sp_name_infers_size_depth_and_default_order(self):
        path = "YUV_1280x720_8bits_420sp_linear_20260810105249.yuv"
        inference = infer_yuv_filename(path)
        metadata = inference.metadata
        self.assertEqual((metadata.width, metadata.height), (1280, 720))
        self.assertEqual(metadata.bit_depth, 8)
        self.assertEqual(metadata.pixel_format, "NV12")
        self.assertIn("Linear Layout", inference.recognized)
        self.assertTrue(any("NV21" in item for item in inference.warnings))

    def test_explicit_nv21_overrides_generic_420sp_default(self):
        metadata = infer_yuv_metadata(
            "capture_1920x1080_8bit_420sp_NV21_BT709_FULL.yuv"
        )
        self.assertEqual(metadata.pixel_format, "NV21")
        self.assertEqual(metadata.color_matrix, "BT.709")
        self.assertEqual(metadata.color_range, "Full")

    def test_10bit_generic_semiplanar_warns_about_container_alignment(self):
        inference = infer_yuv_filename("3840x2160_10bits_420sp.yuv")
        self.assertEqual(inference.metadata.bit_depth, 10)
        self.assertTrue(any("P010" in item for item in inference.warnings))


class YUVReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.y = np.arange(8, dtype=np.uint8).reshape(2, 4) + 16
        self.u = np.array([[80, 90]], np.uint8)
        self.v = np.array([[160, 170]], np.uint8)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, name, *parts):
        path = self.root / name
        path.write_bytes(b"".join(np.asarray(part).tobytes() for part in parts))
        return path

    def test_i420_and_yv12_plane_order(self):
        i420 = self._write("4x2_i420.yuv", self.y, self.u, self.v)
        yv12 = self._write("4x2_yv12.yuv", self.y, self.v, self.u)
        for path, fmt in ((i420, "I420"), (yv12, "YV12")):
            frame = read_yuv_frame(path, YUVMetadata(4, 2, fmt))
            np.testing.assert_array_equal(frame.y, self.y)
            np.testing.assert_array_equal(frame.u, self.u)
            np.testing.assert_array_equal(frame.v, self.v)

    def test_nv12_and_nv21_uv_order(self):
        uv = np.stack((self.u, self.v), axis=-1)
        vu = np.stack((self.v, self.u), axis=-1)
        for fmt, packed in (("NV12", uv), ("NV21", vu)):
            path = self._write(f"4x2_{fmt}.yuv", self.y, packed)
            frame = read_yuv_frame(path, YUVMetadata(4, 2, fmt))
            np.testing.assert_array_equal(frame.u, self.u)
            np.testing.assert_array_equal(frame.v, self.v)

    def test_yuyv_and_uyvy_unpack(self):
        yuyv = np.array(
            [[[16, 80, 17, 160], [18, 90, 19, 170]],
             [[20, 81, 21, 161], [22, 91, 23, 171]]],
            np.uint8,
        )
        uyvy = yuyv[..., [1, 0, 3, 2]]
        expected_u = np.array([[80, 90], [81, 91]], np.uint8)
        expected_v = np.array([[160, 170], [161, 171]], np.uint8)
        for fmt, packed in (("YUYV", yuyv), ("UYVY", uyvy)):
            path = self._write(f"4x2_{fmt}.yuv", packed)
            frame = read_yuv_frame(path, YUVMetadata(4, 2, fmt))
            np.testing.assert_array_equal(frame.y, self.y)
            np.testing.assert_array_equal(frame.u, expected_u)
            np.testing.assert_array_equal(frame.v, expected_v)

    def test_yuv444p_and_yuv422p(self):
        u444 = np.arange(8, dtype=np.uint8).reshape(2, 4) + 90
        v444 = u444 + 40
        path444 = self._write("4x2_yuv444p.yuv", self.y, u444, v444)
        frame444 = read_yuv_frame(path444, YUVMetadata(4, 2, "YUV444P"))
        np.testing.assert_array_equal(frame444.u, u444)
        np.testing.assert_array_equal(frame444.v, v444)

        u422 = np.array([[90, 91], [92, 93]], np.uint8)
        v422 = u422 + 40
        path422 = self._write("4x2_yuv422p.yuv", self.y, u422, v422)
        frame422 = read_yuv_frame(path422, YUVMetadata(4, 2, "YUV422P"))
        np.testing.assert_array_equal(frame422.u, u422)
        np.testing.assert_array_equal(frame422.v, v422)

    def test_gray_creates_neutral_chroma(self):
        path = self._write("4x2_gray.yuv", self.y)
        frame = read_yuv_frame(path, YUVMetadata(4, 2, "GRAY"))
        np.testing.assert_array_equal(frame.u, np.full((2, 4), 128, np.uint8))
        np.testing.assert_array_equal(frame.v, np.full((2, 4), 128, np.uint8))

    def test_p010_and_planar_10_bit(self):
        y10 = (np.arange(8, dtype=np.uint16).reshape(2, 4) + 64)
        u10 = np.array([[400, 420]], np.uint16)
        v10 = np.array([[600, 620]], np.uint16)
        uv10 = np.stack((u10, v10), axis=-1)
        p010 = self._write(
            "4x2_p010.yuv",
            (y10 << 6).astype("<u2"),
            (uv10 << 6).astype("<u2"),
        )
        frame = read_yuv_frame(
            p010, YUVMetadata(4, 2, "P010", bit_depth=10)
        )
        np.testing.assert_array_equal(frame.y, y10)
        np.testing.assert_array_equal(frame.u, u10)
        np.testing.assert_array_equal(frame.v, v10)

        planar = self._write(
            "4x2_yuv420p10le.yuv",
            y10.astype("<u2"),
            u10.astype("<u2"),
            v10.astype("<u2"),
        )
        frame = read_yuv_frame(
            planar,
            YUVMetadata(4, 2, "YUV420P10LE", bit_depth=10),
        )
        np.testing.assert_array_equal(frame.y, y10)
        np.testing.assert_array_equal(frame.u, u10)

    def test_stride_offset_and_multiple_frames(self):
        metadata = YUVMetadata(
            4, 2, "NV12", y_stride=6, uv_stride=6, data_offset=3
        )
        frame_bytes = bytes([
            16, 17, 18, 19, 0, 0,
            20, 21, 22, 23, 0, 0,
            80, 160, 90, 170, 0, 0,
        ])
        path = self.root / "stride.yuv"
        path.write_bytes(b"HDR" + frame_bytes + frame_bytes)
        info = validate_yuv_file(path, metadata)
        self.assertEqual(info.frame_count, 2)
        self.assertEqual(frame_size_bytes(metadata), len(frame_bytes))
        frame = read_yuv_frame(path, metadata, 1)
        np.testing.assert_array_equal(frame.y, self.y)
        self.assertEqual(frame.sample(3, 1), (23, 90, 170))

    def test_invalid_size_dimension_and_frame_are_rejected(self):
        path = self.root / "bad.yuv"
        path.write_bytes(b"123")
        with self.assertRaises(ISPError):
            validate_yuv_file(path, YUVMetadata(4, 2, "NV12"))
        with self.assertRaises(ISPError):
            YUVMetadata(3, 2, "NV12").validate()


class YUVConversionTests(unittest.TestCase):
    @staticmethod
    def _frame(y, u, v, matrix="BT.709", color_range="Limited", depth=8):
        metadata = YUVMetadata(
            2,
            2,
            "YUV444P",
            bit_depth=depth,
            color_matrix=matrix,
            color_range=color_range,
        )
        return YUVFrame(
            np.full((2, 2), y, np.uint16),
            np.full((2, 2), u, np.uint16),
            np.full((2, 2), v, np.uint16),
            metadata,
        )

    def test_limited_black_white_and_neutral_gray(self):
        black = yuv_to_rgb(self._frame(16, 128, 128)).rgb
        white = yuv_to_rgb(self._frame(235, 128, 128)).rgb
        gray = yuv_to_rgb(self._frame(128, 128, 128)).rgb
        np.testing.assert_allclose(black, 0.0, atol=1e-6)
        np.testing.assert_allclose(white, 1.0, atol=1e-6)
        np.testing.assert_allclose(gray[..., 0], gray[..., 1], atol=1e-6)
        np.testing.assert_allclose(gray[..., 1], gray[..., 2], atol=1e-6)

    def test_full_range_and_10_bit_normalization(self):
        self.assertEqual(
            normalize_yuv_sample(
                0, 128, 128, YUVMetadata(color_range="Full")
            ),
            (0.0, 0.0, 0.0),
        )
        yn, un, vn = normalize_yuv_sample(
            64,
            512,
            512,
            YUVMetadata(bit_depth=10, color_range="Limited"),
        )
        self.assertAlmostEqual(yn, 0.0)
        self.assertAlmostEqual(un, 0.0)
        self.assertAlmostEqual(vn, 0.0)

    def test_bt601_bt709_bt2020_are_distinct(self):
        outputs = [
            yuv_to_rgb(self._frame(120, 90, 180, matrix)).rgb[0, 0]
            for matrix in ("BT.601", "BT.709", "BT.2020")
        ]
        self.assertFalse(np.allclose(outputs[0], outputs[1]))
        self.assertFalse(np.allclose(outputs[1], outputs[2]))

    def test_known_bt709_red_vector(self):
        kr, kb = 0.2126, 0.0722
        y = kr
        cb = -kr / (2 * (1 - kb))
        cr = 0.5
        frame = self._frame(
            round(y * 255),
            round(cb * 255 + 128),
            round(cr * 255 + 128),
            color_range="Full",
        )
        rgb = yuv_to_rgb(frame).rgb[0, 0]
        np.testing.assert_allclose(rgb, [1, 0, 0], atol=0.012)

    def test_out_of_range_diagnostics_are_retained_before_clip(self):
        result = yuv_to_rgb(self._frame(120, 16, 240), clip=False)
        self.assertGreater(result.diagnostics["negative_ratio"], 0)
        self.assertGreater(result.diagnostics["overflow_ratio"], 0)

    def test_native_yuv_histogram_uses_original_plane_sample_counts(self):
        frame = self._frame(120, 90, 180)
        rgb = yuv_to_rgb(frame, clip=True).rgb
        histogram = compute_yuv_histogram(frame, rgb)
        self.assertEqual(int(histogram["Y"].sum()), frame.y.size)
        self.assertEqual(int(histogram["U"].sum()), frame.u.size)
        self.assertEqual(int(histogram["V"].sum()), frame.v.size)
        self.assertEqual(int(histogram["R"].sum()), rgb.shape[0] * rgb.shape[1])

    def test_chroma_siting_changes_upsampling_alignment(self):
        metadata = YUVMetadata(
            4, 2, "NV12", chroma_upsampling="Bilinear"
        )
        frame = YUVFrame(
            np.full((2, 4), 128, np.uint8),
            np.array([[16, 240]], np.uint8),
            np.full((1, 2), 128, np.uint8),
            metadata,
        )
        centered = yuv_to_rgb(frame).u_normalized
        frame.metadata.chroma_siting = "Left"
        left = yuv_to_rgb(frame).u_normalized
        self.assertFalse(np.allclose(centered, left))


if __name__ == "__main__":
    unittest.main()
