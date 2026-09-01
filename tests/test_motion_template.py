import tempfile
import unittest
from pathlib import Path

from motion.template import TemplateError, inspect_project, render_template


TEMPLATE = '<motion title="{{MOTION:TITLE}}"><color>{{MOTION:COLOR}}</color></motion>'


class MotionTemplateTests(unittest.TestCase):
    def test_renders_copy_escapes_xml_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "base.motn"); output = Path(directory, "working.motn")
            source.write_text(TEMPLATE, encoding="utf-8")
            result = render_template(source, output, {"TITLE": 'A & "B"', "COLOR": "#fff"})
            self.assertEqual(source.read_text(encoding="utf-8"), TEMPLATE)
            self.assertIn("A &amp; &quot;B&quot;", output.read_text(encoding="utf-8"))
            self.assertTrue(result["xml"])
            self.assertEqual(result["placeholders"], [])

    def test_refuses_missing_unknown_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "base.motn"); output = Path(directory, "working.motn")
            source.write_text(TEMPLATE, encoding="utf-8")
            with self.assertRaisesRegex(TemplateError, "unresolved"):
                render_template(source, output, {"TITLE": "A"})
            with self.assertRaisesRegex(TemplateError, "no matching"):
                render_template(source, output, {"TITLE": "A", "COLOR": "B", "EXTRA": 1})
            render_template(source, output, {"TITLE": "A", "COLOR": "B"})
            with self.assertRaisesRegex(TemplateError, "already exists"):
                render_template(source, output, {"TITLE": "A", "COLOR": "B"})

    def test_inspection_supports_binary_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "binary.motn"); path.write_bytes(b"\xff\x00\x01")
            before = path.read_bytes(); result = inspect_project(path)
            self.assertFalse(result["text"]); self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
