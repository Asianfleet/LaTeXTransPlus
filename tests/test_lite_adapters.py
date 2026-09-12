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

    def __init__(self, pdf_content: bytes = b"%PDF-1.7", stderr: str = "") -> None:
        """Configure the bytes and engine output the fake converter reports."""
        self.command: list[str] = []
        self.pdf_content = pdf_content
        self.stderr = stderr
        self.kwargs: dict[str, object] = {}

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Record the invocation and materialize its requested output file."""
        self.command = command
        self.kwargs = kwargs
        destination = Path(command[command.index("-o") + 1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.pdf_content)
        return subprocess.CompletedProcess(command, 0, "pandoc output", self.stderr)


class FakeHttpStatusError(Exception):
    """Model an httpx-style status error carrying a response status."""

    def __init__(self, status_code: int) -> None:
        """Store a response object exposing only the status code."""
        self.response = types.SimpleNamespace(status_code=status_code)
        super().__init__(
            f"Client error '{status_code} Unauthorized' for url "
            "'https://mineru.net/api/v4/file-urls/batch'"
        )


class FailingPandocRunner:
    """Raise the Pandoc PDF failure that a broken XeLaTeX run reports."""

    def __init__(self, stderr: str, returncode: int = 43) -> None:
        """Store the captured engine output and exit status."""
        self.stderr = stderr
        self.returncode = returncode
        self.command: list[str] = []

    def __call__(
        self, command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Fail the conversion the way ``subprocess.run(check=True)`` does."""
        self.command = command
        raise subprocess.CalledProcessError(
            self.returncode, command, output="", stderr=self.stderr
        )


class RejectingMineruClient:
    """Reject every extraction with a modeled HTTP status error."""

    def __init__(self, status_code: int = 401) -> None:
        """Store the HTTP status returned by the fake MinerU service."""
        self.status_code = status_code

    def extract(self, source_pdf: str) -> object:
        """Raise the configured HTTP status without returning a result."""
        raise FakeHttpStatusError(self.status_code)


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
        result = MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(result, self.output_dir / "source.md")
        self.assertEqual(result.read_text(encoding="utf-8"), "# Title\n![x](images/a.png)")
        self.assertEqual((self.output_dir / "images" / "a.png").read_bytes(), b"png")
        self.assertEqual(client.source_pdf, "source.pdf")

    def test_mineru_default_factory_passes_the_resolved_token_to_the_sdk(self) -> None:
        """Resolve the configured env var and pass its token to ``mineru.MinerU``."""
        from src.engines.lite_mineru import _create_default_mineru_client

        observed_tokens: list[str | None] = []

        class ActualSdkMinerU:
            """Stand in for MinerU Open SDK's public client class."""

            def __init__(self, token: str | None = None) -> None:
                """Record the token resolved by the lite adapter."""
                observed_tokens.append(token)

        sdk_module = types.ModuleType("mineru")
        sdk_module.MinerU = ActualSdkMinerU

        with patch.dict(sys.modules, {"mineru": sdk_module}):
            with patch.dict("os.environ", {"LATEXTRANS_TEST_MINERU_TOKEN": "secret"}):
                client = _create_default_mineru_client("LATEXTRANS_TEST_MINERU_TOKEN")

        self.assertIsInstance(client, ActualSdkMinerU)
        self.assertEqual(observed_tokens, ["secret"])

    def test_mineru_default_factory_rejects_a_missing_token_env(self) -> None:
        """A missing configured token env var should fail before contacting MinerU."""
        from src.engines.lite_mineru import _create_default_mineru_client

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "MISSING_MINERU_TOKEN") as raised:
                _create_default_mineru_client("MISSING_MINERU_TOKEN")

        self.assertIn("No MINERU-related environment variable", str(raised.exception))
        self.assertIn("restart the TUI", str(raised.exception))

    def test_mineru_missing_token_error_lists_related_names_without_values(self) -> None:
        """Diagnose name mismatches by listing visible MINERU names only."""
        from src.engines.lite_mineru import _create_default_mineru_client

        with patch.dict("os.environ", {"MINERU_API_KEY": "secret-value"}, clear=True):
            with self.assertRaises(ValueError) as raised:
                _create_default_mineru_client("MINERU_TOKEN")

        message = str(raised.exception)
        self.assertIn("MINERU_API_KEY", message)
        self.assertNotIn("secret-value", message)

    def test_mineru_adapter_forwards_the_configured_api_key_env(self) -> None:
        """Pass the lite config's token env var name through to the client factory."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        observed_envs: list[str] = []
        client = FakeMineruClient(markdown="# Title", resources={})

        def record_env(api_key_env: str) -> FakeMineruClient:
            """Record the configured token env var and return the fake client."""
            observed_envs.append(api_key_env)
            return client

        MineruMarkdownExtractor(client_factory=record_env).extract(
            Path("source.pdf"),
            self.output_dir,
            "CUSTOM_MINERU_TOKEN",
        )

        self.assertEqual(observed_envs, ["CUSTOM_MINERU_TOKEN"])

    def test_mineru_token_sanitizer_removes_shell_quoting_and_bearer_prefix(self) -> None:
        """Normalize the common Windows and PowerShell token mistakes."""
        from src.engines.lite_mineru import _sanitize_token

        self.assertEqual(_sanitize_token('"abc"'), "abc")
        self.assertEqual(_sanitize_token("'abc'"), "abc")
        self.assertEqual(_sanitize_token("Bearer abc"), "abc")
        self.assertEqual(_sanitize_token('Bearer "abc"'), "abc")
        self.assertEqual(_sanitize_token("  abc\n"), "abc")
        self.assertEqual(_sanitize_token(""), "")

    def test_mineru_default_factory_passes_a_sanitized_token_to_the_sdk(self) -> None:
        """Quoted environment values must reach the SDK without their quotes."""
        from src.engines.lite_mineru import _create_default_mineru_client

        observed_tokens: list[str | None] = []

        class ActualSdkMinerU:
            """Stand in for MinerU Open SDK's public client class."""

            def __init__(self, token: str | None = None) -> None:
                """Record the sanitized token passed by the lite adapter."""
                observed_tokens.append(token)

        sdk_module = types.ModuleType("mineru")
        sdk_module.MinerU = ActualSdkMinerU

        with patch.dict(sys.modules, {"mineru": sdk_module}):
            with patch.dict(
                "os.environ",
                {"LATEXTRANS_TEST_MINERU_TOKEN": '"secret"'},
                clear=True,
            ):
                _create_default_mineru_client("LATEXTRANS_TEST_MINERU_TOKEN")

        self.assertEqual(observed_tokens, ["secret"])

    def test_mineru_adapter_reports_a_rejected_token_with_the_env_var_name(self) -> None:
        """A 401 from MinerU should name the configured token environment variable."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        extractor = MineruMarkdownExtractor(
            client_factory=lambda _api_key_env: RejectingMineruClient(401)
        )

        with self.assertRaisesRegex(RuntimeError, "MINERU_TOKEN") as raised:
            extractor.extract(Path("source.pdf"), self.output_dir, "MINERU_TOKEN")

        self.assertIn("401", str(raised.exception))
        self.assertFalse((self.output_dir / "source.md").exists())

    def test_mineru_adapter_keeps_non_auth_client_errors_unwrapped(self) -> None:
        """Non-auth client failures must keep their original type and message."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        class FailingClient:
            """Raise a non-HTTP error from ``extract``."""

            def extract(self, source_pdf: str) -> object:
                """Simulate an unrelated adapter failure."""
                raise ValueError("unexpected payload")

        extractor = MineruMarkdownExtractor(
            client_factory=lambda _api_key_env: FailingClient()
        )

        with self.assertRaisesRegex(ValueError, "unexpected payload"):
            extractor.extract(Path("source.pdf"), self.output_dir)

    def test_mineru_adapter_passes_a_string_path_to_sdk_extract(self) -> None:
        """Pass local PDF input using the string argument required by SDK ``extract``."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(
            FakeSdkExtractResult(markdown="# Title", images=[]),
            require_string_source=True,
        )

        MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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

        MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
            Path("source.pdf"), self.output_dir
        )

        self.assertEqual(
            (self.output_dir / "images" / "figure-1.png").read_bytes(), b"png"
        )

    def test_mineru_adapter_accepts_an_empty_sdk_image_list(self) -> None:
        """Persist Markdown when the SDK returns no extracted images."""
        from src.engines.lite_mineru import MineruMarkdownExtractor

        client = FakeSdkClient(FakeSdkExtractResult(markdown="# Title", images=[]))

        result = MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
            MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
            MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
                MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
            MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
                MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
            MineruMarkdownExtractor(client_factory=lambda _api_key_env: client).extract(
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
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            },
        )

    def test_pandoc_adapter_rejects_an_empty_pdf_output(self) -> None:
        """Reject a successful process result that did not produce a usable PDF."""
        from src.engines.lite_pdf import PandocPdfGenerator

        with self.assertRaisesRegex(ValueError, "missing or empty"):
            PandocPdfGenerator(runner=FakePandocRunner(pdf_content=b"")).generate(
                Path("translated.md"), self.output_dir / "translated.pdf", "en"
            )

    def test_pandoc_adapter_reports_the_pdf_engine_output_on_failure(self) -> None:
        """A failed PDF run must keep the exit status and engine output for diagnosis."""
        from src.engines.lite_pdf import PandocPdfError, PandocPdfGenerator

        runner = FailingPandocRunner(
            "! Double superscript.\nl.328 ... x ^ { \\prime } ^\n"
        )

        with self.assertRaises(PandocPdfError) as raised:
            PandocPdfGenerator(runner=runner).generate(
                Path("translated.md"), self.output_dir / "translated.pdf", "ch"
            )

        message = str(raised.exception)
        self.assertEqual(raised.exception.returncode, 43)
        self.assertIn("exit code 43", message)
        self.assertIn("Double superscript", message)
        self.assertIn("l.328", raised.exception.stderr)

    def test_pandoc_adapter_keeps_the_tail_of_a_long_engine_log(self) -> None:
        """Only the tail of a long XeLaTeX log is useful, so the head is dropped."""
        from src.engines.lite_pdf import PandocPdfError, PandocPdfGenerator

        stderr = "\n".join(f"payload {index:02d}" for index in range(60))
        runner = FailingPandocRunner(f"{stderr}\n! Final error")

        with self.assertRaises(PandocPdfError) as raised:
            PandocPdfGenerator(runner=runner).generate(
                Path("translated.md"), self.output_dir / "translated.pdf", "ch"
            )

        message = str(raised.exception)
        self.assertIn("! Final error", message)
        self.assertNotIn("payload 00", message)
        self.assertIn("payload 00", raised.exception.stderr)

    def test_pandoc_adapter_resolves_resources_from_the_document_directory(self) -> None:
        """Relative figure paths must resolve against the Markdown directory."""
        from src.engines.lite_pdf import PandocPdfGenerator

        runner = FakePandocRunner()
        PandocPdfGenerator(runner=runner).generate(
            self.output_dir / "translated.md", self.output_dir / "translated.pdf", "ch"
        )

        self.assertIn(
            f"--resource-path={self.output_dir.resolve()}",
            runner.command,
        )

    def test_pandoc_adapter_uses_the_configured_geometry_and_cjk_font(self) -> None:
        """Explicit geometry and CJK font settings must reach Pandoc as variables."""
        from src.engines.lite_pdf import PandocPdfGenerator

        runner = FakePandocRunner()
        PandocPdfGenerator(
            runner=runner,
            cjk_mainfont="FandolSong",
            geometry="margin=2cm",
        ).generate(Path("translated.md"), self.output_dir / "translated.pdf", "ch")

        self.assertIn("-V", runner.command)
        self.assertIn("geometry:margin=2cm", runner.command)
        self.assertIn("CJKmainfont:FandolSong", runner.command)

    def test_pandoc_adapter_omits_the_cjk_font_for_non_cjk_targets(self) -> None:
        """A Latin target must not receive the CJK font variable."""
        from src.engines.lite_pdf import PandocPdfGenerator

        runner = FakePandocRunner()
        PandocPdfGenerator(runner=runner, cjk_mainfont="FandolSong").generate(
            Path("translated.md"), self.output_dir / "translated.pdf", "fr"
        )

        self.assertNotIn("CJKmainfont:FandolSong", runner.command)

    def test_pandoc_adapter_reports_dropped_glyphs_from_a_successful_run(self) -> None:
        """A zero exit code with missing glyphs must still raise a quality warning."""
        from src.engines.lite_pdf import PandocPdfGenerator

        runner = FakePandocRunner(
            pdf_content=b"%PDF-1.7",
            stderr=(
                "[WARNING] Missing character: There is no 用 (U+7528) in font [lmroman12]\n"
                "[WARNING] Missing character: There is no 于 (U+4E8E) in font [lmroman12]\n"
            ),
        )
        generator = PandocPdfGenerator(runner=runner)

        generator.generate(Path("translated.md"), self.output_dir / "out.pdf", "ch")

        self.assertIn("2 missing character warning", generator.last_pdf_warning)
        self.assertIn("U+7528", generator.last_pdf_warning)

    def test_pandoc_adapter_keeps_a_clean_run_free_of_warnings(self) -> None:
        """A run without dropped glyphs must not report a quality warning."""
        from src.engines.lite_pdf import PandocPdfGenerator

        generator = PandocPdfGenerator(runner=FakePandocRunner(stderr=""))

        generator.generate(Path("translated.md"), self.output_dir / "out.pdf", "ch")

        self.assertEqual(generator.last_pdf_warning, "")


if __name__ == "__main__":
    unittest.main()
