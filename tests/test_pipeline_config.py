import tempfile
import unittest
from pathlib import Path

from isp_tool.config import load_config, save_config
from isp_tool.pipeline import ISPPipeline
from isp_tool.raw_io import synthetic_bayer


class PipelineConfigTests(unittest.TestCase):
    def test_pipeline_produces_all_intermediate_results(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        results = pipeline.process(source.image, source.domain, source.metadata)
        self.assertEqual(len(results), len(pipeline.modules) + 1)
        self.assertEqual(results[0].domain, "bayer")
        self.assertEqual(results[-1].domain, "rgb")
        self.assertEqual(results[-1].image.shape, (120, 160, 3))

    def test_config_round_trip(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        pipeline.module_by_id("white_balance").parameters["r_gain"] = 2.345
        pipeline.module_by_id("color_correction_matrix").enabled = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            save_config(str(path), source.metadata, pipeline)
            data = load_config(str(path))
            restored = ISPPipeline()
            restored.load_snapshot(data["pipeline"])
            self.assertEqual(
                restored.module_by_id("white_balance").parameters["r_gain"], 2.345
            )
            self.assertFalse(
                restored.module_by_id(
                    "color_correction_matrix"
                ).enabled
            )

    def test_incremental_processing_reuses_unchanged_prefix(self):
        source = synthetic_bayer(160, 120)
        pipeline = ISPPipeline()
        cache = {}
        first_snapshot = pipeline.snapshot()
        first = pipeline.process_cached(
            source.image, source.domain, source.metadata, first_snapshot, cache, 1
        )
        pipeline.module_by_id(
            "color_correction_matrix"
        ).parameters["strength"] = 0.8
        second = pipeline.process_cached(
            source.image, source.domain, source.metadata, pipeline.snapshot(), cache, 1
        )
        ccm_index = next(
            index for index, module in enumerate(pipeline.modules)
            if module.module_id == "color_correction_matrix"
        )
        # Result zero is the input; every stage before CCM is reused.
        for result_index in range(ccm_index + 1):
            self.assertIs(first[result_index], second[result_index])
        self.assertIsNot(first[ccm_index + 1], second[ccm_index + 1])


if __name__ == "__main__":
    unittest.main()
