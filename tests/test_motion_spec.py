import tempfile
import unittest
from pathlib import Path

from motion.spec import SpecError, validate_spec


def sample_spec():
    return {
        "version": 1,
        "project": {"name": "Test", "width": 1920, "height": 1080, "fps": 30, "duration": 2, "background": "#000000"},
        "layers": [{"id": "title", "type": "text", "text": "Hello", "start": 0, "duration": 2,
                    "keyframes": [{"time": 0, "property": "opacity", "value": 0},
                                  {"time": 0.3, "property": "opacity", "value": 1, "easing": "ease_out"}]}],
    }


class MotionSpecTests(unittest.TestCase):
    def test_normalizes_frames_and_defaults(self):
        normalized = validate_spec(sample_spec())
        self.assertEqual(normalized["project"]["duration_frames"], 60)
        self.assertEqual(normalized["layers"][0]["position"], [960, 540])
        self.assertEqual(normalized["layers"][0]["duration_frames"], 60)

    def test_rejects_duplicate_ids(self):
        spec = sample_spec(); spec["layers"].append(dict(spec["layers"][0]))
        with self.assertRaisesRegex(SpecError, "duplicate"):
            validate_spec(spec)

    def test_rejects_keyframe_outside_layer(self):
        spec = sample_spec(); spec["layers"][0]["keyframes"][1]["time"] = 3
        with self.assertRaisesRegex(SpecError, "exceeds"):
            validate_spec(spec)

    def test_optional_asset_check(self):
        spec = sample_spec(); spec["layers"] = [{"id": "logo", "type": "image", "asset": "logo.png", "duration": 2}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SpecError, "does not exist"):
                validate_spec(spec, base_dir=directory, check_assets=True)
            Path(directory, "logo.png").write_bytes(b"png")
            self.assertEqual(validate_spec(spec, base_dir=directory, check_assets=True)["layers"][0]["id"], "logo")


if __name__ == "__main__":
    unittest.main()
