import io
import sys
import tempfile
import unittest
from pathlib import Path

from main import _project_log_path, _tee_console_to_log


class CliLogTests(unittest.TestCase):
    def test_project_log_path_uses_translated_project_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = _project_log_path(
                output_dir=tmp_dir,
                target_language="ch",
                project_dir=str(Path("tex source") / "2510.14901"),
            )

        self.assertEqual(log_path, Path(tmp_dir) / "ch_2510.14901" / "latextrans.log")

    def test_tee_console_to_log_preserves_console_output_and_writes_log(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "latextrans.log"

            with _tee_console_to_log(log_path, stdout=stdout, stderr=stderr):
                print("stdout message")
                print("stderr message", file=sys.stderr)

            log_text = log_path.read_text(encoding="utf-8")

        self.assertIn("stdout message", stdout.getvalue())
        self.assertIn("stderr message", stderr.getvalue())
        self.assertIn("stdout message", log_text)
        self.assertIn("stderr message", log_text)


if __name__ == "__main__":
    unittest.main()
