import tempfile
import unittest
from datetime import datetime
from pathlib import Path


class LiteInputTests(unittest.TestCase):
    """Cover lite PDF input recognition and self-contained project setup."""

    def setUp(self):
        """Create an isolated output root for each test."""
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.output_root = Path(self._temporary_directory.name) / "output-lite"

    def tearDown(self):
        """Remove the isolated output root after each test."""
        self._temporary_directory.cleanup()

    def test_arxiv_id_and_urls_normalize_to_arxiv_pdf(self):
        """Recognize IDs and arXiv pages as equivalent PDF inputs."""
        from src.engines.lite_inputs import parse_lite_input

        for value in (
            "2508.18791v2",
            "https://arxiv.org/abs/2508.18791v2",
            "https://arxiv.org/pdf/2508.18791v2.pdf",
        ):
            spec = parse_lite_input(value)
            self.assertEqual(spec.kind, "arxiv")
            self.assertEqual(spec.stable_name, "2508.18791v2")
            self.assertEqual(spec.url, "https://arxiv.org/pdf/2508.18791v2.pdf")

    def test_non_arxiv_url_is_pdf_url_with_safe_stable_name(self):
        """Treat ordinary HTTP URLs as PDF downloads with safe directory names."""
        from src.engines.lite_inputs import parse_lite_input

        spec = parse_lite_input("https://example.org/papers/report%20draft.pdf?token=x")

        self.assertEqual(spec.kind, "pdf_url")
        self.assertEqual(spec.stable_name, "report_draft")
        self.assertEqual(spec.url, "https://example.org/papers/report%20draft.pdf?token=x")

    def test_local_input_requires_a_pdf_suffix(self):
        """Reject local input values that cannot designate PDF files."""
        from src.engines.lite_inputs import parse_lite_input

        self.assertEqual(parse_lite_input("paper.PDF").kind, "local_pdf")
        with self.assertRaisesRegex(ValueError, "PDF"):
            parse_lite_input("paper.tex")

    def test_input_rejects_empty_and_multiple_items(self):
        """Accept exactly one nonempty lite input item per task."""
        from src.engines.lite_inputs import parse_lite_input

        for value in ("", "\n", "one.pdf,two.pdf", "one.pdf\ntwo.pdf"):
            with self.assertRaises(ValueError):
                parse_lite_input(value)

    def test_project_directory_uses_stable_name_date_and_source_name(self):
        """Create a date-suffixed project directory for downloaded arXiv PDFs."""
        from src.engines.lite_inputs import parse_lite_input, prepare_lite_project

        prepared = prepare_lite_project(
            parse_lite_input("2508.18791"),
            self.output_root,
            now=datetime(2026, 9, 9, 20, 30, 0),
            download_pdf=lambda url, destination: destination.write_bytes(b"%PDF-1.7"),
        )

        self.assertEqual(prepared.project_dir.name, "2508.18791_260909")
        self.assertEqual(prepared.project_name, "2508.18791_260909")
        self.assertEqual(prepared.source_pdf.name, "source.pdf")
        self.assertEqual(prepared.source_pdf.read_bytes(), b"%PDF-1.7")
        self.assertEqual(prepared.input_item, "2508.18791")
        self.assertEqual(prepared.input_type, "arxiv")

    def test_same_day_project_gets_numeric_suffix(self):
        """Avoid overwriting an already-created same-day project directory."""
        from src.engines.lite_inputs import parse_lite_input, prepare_lite_project

        spec = parse_lite_input("2508.18791")
        timestamp = datetime(2026, 9, 9, 20, 30, 0)
        first = prepare_lite_project(
            spec,
            self.output_root,
            now=timestamp,
            download_pdf=lambda url, destination: destination.write_bytes(b"first"),
        )
        second = prepare_lite_project(
            spec,
            self.output_root,
            now=timestamp,
            download_pdf=lambda url, destination: destination.write_bytes(b"second"),
        )

        self.assertEqual(first.project_dir.name, "2508.18791_260909")
        self.assertEqual(second.project_dir.name, "2508.18791_260909_1")
        self.assertEqual(first.source_pdf.read_bytes(), b"first")
        self.assertEqual(second.source_pdf.read_bytes(), b"second")

    def test_local_pdf_is_copied_into_the_project_directory(self):
        """Copy local PDFs so every lite project owns its source artifact."""
        from src.engines.lite_inputs import parse_lite_input, prepare_lite_project

        local_pdf = Path(self._temporary_directory.name) / "论文 文件.pdf"
        local_pdf.write_bytes(b"%PDF-local")

        prepared = prepare_lite_project(
            parse_lite_input(str(local_pdf)),
            self.output_root,
            now=datetime(2026, 9, 9, 20, 30, 0),
        )

        self.assertEqual(prepared.project_dir.name, "论文_文件_260909")
        self.assertEqual(prepared.source_pdf.read_bytes(), b"%PDF-local")
        self.assertEqual(prepared.input_type, "local_pdf")

    def test_prepare_rejects_missing_or_non_file_local_pdf(self):
        """Reject absent paths and directories before they become project sources."""
        from src.engines.lite_inputs import parse_lite_input, prepare_lite_project

        missing = parse_lite_input(str(Path(self._temporary_directory.name) / "missing.pdf"))
        directory = Path(self._temporary_directory.name) / "folder.pdf"
        directory.mkdir()
        not_a_file = parse_lite_input(str(directory))

        with self.assertRaisesRegex(ValueError, "file"):
            prepare_lite_project(missing, self.output_root)
        with self.assertRaisesRegex(ValueError, "file"):
            prepare_lite_project(not_a_file, self.output_root)

    def test_download_failure_removes_partial_source_pdf(self):
        """Remove incomplete downloads when the injected downloader raises an error."""
        from src.engines.lite_inputs import (
            LiteProjectPreparationError,
            parse_lite_input,
            prepare_lite_project,
        )

        def fail_after_partial_write(url, destination):
            """Simulate a network interruption after a partial write."""
            del url
            destination.write_bytes(b"partial")
            raise OSError("connection reset")

        with self.assertRaisesRegex(LiteProjectPreparationError, "download") as raised:
            prepare_lite_project(
                parse_lite_input("https://example.org/report.pdf"),
                self.output_root,
                now=datetime(2026, 9, 9, 20, 30, 0),
                download_pdf=fail_after_partial_write,
            )

        project_dir = self.output_root / "report_260909"
        self.assertEqual(raised.exception.project_dir, project_dir)
        self.assertEqual(raised.exception.project_name, project_dir.name)
        self.assertTrue(project_dir.is_dir())
        self.assertFalse((project_dir / "source.pdf").exists())

    def test_http_get_dependency_streams_remote_pdf_without_real_network(self):
        """Use the injected HTTP getter when no direct downloader is supplied."""
        from src.engines.lite_inputs import parse_lite_input, prepare_lite_project

        class FakeResponse:
            """Provide the subset of a streamed HTTP response used by the downloader."""

            def raise_for_status(self):
                """Model a successful HTTP response."""

            def iter_content(self, chunk_size):
                """Yield deterministic PDF bytes in stream-sized chunks."""
                if chunk_size != 8192:
                    raise AssertionError("Unexpected chunk size")
                yield b"%PDF-"
                yield b"remote"

        calls = []

        def fake_get(url, **kwargs):
            """Record the expected streamed request and return a fake response."""
            calls.append((url, kwargs))
            return FakeResponse()

        prepared = prepare_lite_project(
            parse_lite_input("https://example.org/report.pdf"),
            self.output_root,
            http_get=fake_get,
            now=datetime(2026, 9, 9, 20, 30, 0),
        )

        self.assertEqual(prepared.source_pdf.read_bytes(), b"%PDF-remote")
        self.assertEqual(
            calls,
            [("https://example.org/report.pdf", {"stream": True, "timeout": 30})],
        )


if __name__ == "__main__":
    unittest.main()
