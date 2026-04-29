import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class CliOnlyDistributionTests(unittest.TestCase):
    def test_package_exposes_only_cli_entry_point(self):
        setup_tree = ast.parse((PROJECT_ROOT / "setup.py").read_text(encoding="utf-8"))
        setup_call = next(
            node
            for node in ast.walk(setup_tree)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup"
        )
        entry_points = next(
            keyword.value
            for keyword in setup_call.keywords
            if keyword.arg == "entry_points"
        )
        console_scripts = next(
            value
            for key, value in zip(entry_points.keys, entry_points.values)
            if key.value == "console_scripts"
        )
        scripts = [item.value for item in console_scripts.elts]

        self.assertEqual(scripts, ["latextrans=main:main"])

    def test_requirements_do_not_include_streamlit(self):
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertNotIn("streamlit", requirements.lower())

    def test_gui_package_is_removed(self):
        self.assertFalse((PROJECT_ROOT / "src" / "gui").exists())


if __name__ == "__main__":
    unittest.main()
