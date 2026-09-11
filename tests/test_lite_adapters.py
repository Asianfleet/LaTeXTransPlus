"""Tests for lite-engine MinerU and Pandoc boundary adapters."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


class FakeMineruClient:
    """Return a deterministic parsed document without contacting MinerU."""

    def __init__(self, markdown: str | None, resources: dict[str, bytes]) -> None:
        """Store the document result returned from ``extract``."""
        self.markdown = markdown
        self.resources = resources
        self.source_pdf: str | None = None

    def extract(self, source_pdf: str) -> dict[str, object]:
        """Return the configured Markdown and resource mapping."""
        self.source_pdf = source_pdf
        return {"markdown": self.markdown, "resources": self.resources}


@dataclass
class FakeSdkImage:
    """Model an image returned by MinerU Open SDK 0.2.5."""

    name: str
    data: bytes
    path: str


@dataclass
class FakeSdkExtractResult:
    """Model the Markdown and image fields exposed by the real SDK result."""

    markdown: str | None
    images: list[FakeSdkImage]


class FakeSdkClient:
    """Return an SDK-shaped extraction result while recording its source argument."""

    def __init__(self, result: FakeSdkExtractResult, require_string_source: bool = False) -> None:
        """Store the configured result and optionally enforce the SDK source type."""
        self.result = result
        self.require_string_source = require_string_source
        self.source: str | Path | None = None

    def extract(self, source: str | Path) -> FakeSdkExtractResult:
        """Return the configured result after validating the supplied source path."""
        if self.require_string_source and not isinstance(source, str):
            raise TypeError("MinerU SDK source must be a string.")
        self.source = source
        return self.result


class FakePandocRunner:
    """Record a Pandoc command and create the requested PDF fixture."""

    def __init__(self, pdf_content: bytes = b"%PDF-1.7") -> None:
        """Configure the bytes the fake converter writes."""
        self.command: list[str] = []
        self.pdf_content = pdf_content
        self.kwargs: dict[str, object] = {}

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Record the invocation and materialize its requested output file."""
        self.command = command
        self.kwargs = kwargs
        destination = Path(command[command.index("-o") + 1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.pdf_content)
        return subprocess.CompletedProcess(command, 0, "pandoc output", "")


class LiteAdapterTests(unittest.TestCase):
    """Exercise adapters through their injected external-service boundaries."""

    def setUp(self) -> None:
        """Create an isolated directory for each adapter output."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        """Remove the isolated adapter output directory."""
        self.temporary_directory.cleanup()

    def test_mineru_adapter_writes_markdown_and_resources(self) -> None:
        """Persist a parsed MinerU document under the project directory."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeMineruClient(
            markdown="# Title\n![x](images/a.png)",
            resources={"images/a.png": b"png"},
        )
        result = MineruMarkdownExtractor(client_factory=lambda: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(result, self.output_dir / "source.md")
        self.assertEqual(result.read_text(encoding="utf-8"), "# Title\n![x](images/a.png)")
        self.assertEqual((self.output_dir / "images" / "a.png").read_bytes(), b"png")
        self.assertEqual(client.source_pdf, "source.pdf")

    def test_mineru_default_factory_constructs_the_sdk_mineru_client(self) -> None:
        """Construct the public ``mineru.MinerU`` client exported by SDK 0.2.5."""
        from src.engines.lite_mineru import _create_default_mineru_client

        class ActualSdkMinerU:
            """Stand in for MinerU Open SDK's public client class."""

        sdk_module = types.ModuleType("mineru")
        sdk_module.MinerU = ActualSdkMinerU

        with patch.dict(sys.modules, {"mineru": sdk_module}):
            self.assertIsInstance(_create_default_mineru_client(), ActualSdkMinerU)

    def test_mineru_adapter_passes_a_string_path_to_sdk_extract(self) -> None:
        """Pass local PDF input using the string argument required by SDK ``extract``."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(markdown="# Title", images=[]),
            require_string_source=True,
        )

        MineruMarkdownExtractor(client_factory=lambda: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(client.source, "source.pdf")

    def test_mineru_adapter_writes_sdk_image_list_to_each_declared_path(self) -> None:
        """Persist SDK ``Image.path`` and ``Image.data`` values below the output directory."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(
                markdown="# Title\n![figure](images/figure-1.png)",
                images=[
                    FakeSdkImage(
                        name="figure-1.png",
                        data=b"png",
                        path="images/figure-1.png",
                    )
                ],
            )
        )

        MineruMarkdownExtractor(client_factory=lambda: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(
            (self.output_dir / "images" / "figure-1.png").read_bytes(), b"png"
        )

    def test_mineru_adapter_accepts_an_empty_sdk_image_list(self) -> None:
        """Persist Markdown when the SDK returns no extracted images."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(FakeSdkExtractResult(markdown="# Title", images=[]))

        result = MineruMarkdownExtractor(client_factory=lambda: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(result.read_text(encoding="utf-8"), "# Title")

    def test_mineru_adapter_rejects_a_traversal_sdk_image_path(self) -> None:
        """Reject SDK image paths that would escape the project output directory."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(
                markdown="# Title",
                images=[FakeSdkImage("outside.png", b"png", "../outside.png")],
            )
        )

        with self.assertRaisesRegex(ValueError, "unsafe"):
            MineruMarkdownExtractor(client_factory=lambda: client).extract(
                Path("source.pdf"), self.output_dir
            )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir.parent / "outside.png").exists())

    def test_mineru_adapter_rejects_non_bytes_sdk_image_data(self) -> None:
        """Reject malformed SDK image data and remove its partial Markdown output."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(
                markdown="# Title",
                images=[FakeSdkImage("figure.png", object(), "images/figure.png")],
            )
        )

        with self.assertRaisesRegex(TypeError, "bytes-like"):
            MineruMarkdownExtractor(client_factory=lambda: client).extract(
                Path("source.pdf"), self.output_dir
            )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir / "images" / "figure.png").exists())
        self.assertFalse((self.output_dir / "images").exists())

    def test_mineru_adapter_cleans_all_nested_sdk_image_directories_on_write_failure(
        self,
    ) -> None:
        """Remove every newly created image directory after a failed SDK image write."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(
                markdown="# Title",
                images=[
                    FakeSdkImage("a.png", b"a", "images/nested/a.png"),
                    FakeSdkImage("b.png", b"b", "images/nested/b.png"),
                ],
            )
        )
        original_write_bytes = Path.write_bytes

        def fail_on_second_image(path: Path, content: bytes) -> int:
            """Partially write the second image before reporting a disk failure."""
            if path.name == "b.png":
                original_write_bytes(path, content[:1])
                raise OSError("disk full")
            return original_write_bytes(path, content)

        with patch.object(Path, "write_bytes", new=fail_on_second_image):
            with self.assertRaisesRegex(OSError, "disk full"):
                MineruMarkdownExtractor(client_factory=lambda: client).extract(
                    Path("source.pdf"), self.output_dir
                )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir / "images" / "nested" / "a.png").exists())
        self.assertFalse((self.output_dir / "images" / "nested" / "b.png").exists())
        self.assertFalse((self.output_dir / "images" / "nested").exists())
        self.assertFalse((self.output_dir / "images").exists())

    def test_mineru_adapter_rejects_empty_markdown_and_cleans_resources(self) -> None:
        """Avoid leaving artifacts when MinerU returns no usable Markdown."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeMineruClient(markdown="   \n", resources={"images/a.png": b"png"})

        with self.assertRaisesRegex(ValueError, "Markdown"):
            MineruMarkdownExtractor(client_factory=lambda: client).extract(
                Path("source.pdf"), self.output_dir
            )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir / "images" / "a.png").exists())

    def test_mineru_adapter_cleans_written_files_after_resource_write_failure(self) -> None:
        """Remove every resource when a partially written resource raises ``OSError``."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeMineruClient(
            markdown="# Title",
            resources={"images/a.png": b"a", "images/b.png": b"b"},
        )
        original_write_bytes = Path.write_bytes

        def fail_on_second_resource(path: Path, content: bytes) -> int:
            """Write part of the second image before simulating a disk-full error."""
            if path.name == "b.png":
                original_write_bytes(path, content[:1])
                raise OSError("disk full")
            return original_write_bytes(path, content)

        with patch.object(Path, "write_bytes", new=fail_on_second_resource):
            with self.assertRaisesRegex(OSError, "disk full"):
                MineruMarkdownExtractor(client_factory=lambda: client).extract(
                    Path("source.pdf"), self.output_dir
                )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir / "images" / "a.png").exists())
        self.assertFalse((self.output_dir / "images" / "b.png").exists())
        self.assertFalse((self.output_dir / "images").exists())

    def test_mineru_adapter_cleans_files_after_resource_content_normalization_failure(self) -> None:
        """Remove Markdown and prior resources when resource bytes cannot be normalized."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeMineruClient(
            markdown="# Title",
            resources={"images/a.png": b"a", "images/b.png": object()},
        )

        with self.assertRaisesRegex(TypeError, "bytes-like"):
            MineruMarkdownExtractor(client_factory=lambda: client).extract(
                Path("source.pdf"), self.output_dir
            )

        self.assertFalse((self.output_dir / "source.md").exists())
        self.assertFalse((self.output_dir / "images" / "a.png").exists())
        self.assertFalse((self.output_dir / "images").exists())

    def test_pandoc_adapter_generates_pdf_with_xelatex_and_language_metadata(self) -> None:
        """Use XeLaTeX and a language-specific Pandoc argument for CJK output."""
        from src.engines.lite_pdf import PandocPdfGenerator

        runner = FakePandocRunner()
        result = PandocPdfGenerator(runner=runner).generate(
            Path("translated.md"), self.output_dir / "translated.pdf", "ch"
        )

        self.assertEqual(result.name, "translated.pdf")
        self.assertIn("--pdf-engine=xelatex", runner.command)
        self.assertIn("--metadata=lang:zh-CN", runner.command)
        self.assertEqual(
            runner.kwargs,
            {"check": True, "capture_output": True, "text": True},
        )

    def test_pandoc_adapter_rejects_an_empty_pdf_output(self) -> None:
        """Reject a successful process result that did not produce a usable PDF."""
        from src.engines.lite_pdf import PandocPdfGenerator

        with self.assertRaisesRegex(ValueError, "missing or empty"):
            PandocPdfGenerator(runner=FakePandocRunner(pdf_content=b"")).generate(
                Path("translated.md"), self.output_dir / "translated.pdf", "en"
            )


if __name__ == "__main__":
    unittest.main()
