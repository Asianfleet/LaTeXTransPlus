import asyncio
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agents.tool_agents.markdown_translator_agent import MarkdownTranslatorAgent
from src.engines.lite_markdown import MarkdownBlock, split_markdown
from src.terminology import write_project_terms_csv


class _FakeProviderResponse:
    """Implement the aiohttp response context used by provider requests."""

    def __init__(self, content: str) -> None:
        """Store the translated content returned by the fake provider."""
        self._content = content

    async def __aenter__(self) -> "_FakeProviderResponse":
        """Enter the fake response context."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """Exit the fake response context without suppressing exceptions."""

    def raise_for_status(self) -> None:
        """Accept the fake provider response as successful."""

    async def json(self) -> dict[str, object]:
        """Return a chat-completions-compatible response body."""
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeProviderSession:
    """Capture provider requests through the aiohttp session interface."""

    def __init__(self, content: str) -> None:
        """Initialize request capture and the fixed provider response."""
        self.content = content
        self.requests: list[dict[str, object]] = []

    async def __aenter__(self) -> "_FakeProviderSession":
        """Enter the fake client session context."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """Exit the fake client session context without suppressing exceptions."""

    def post(self, url: str, **kwargs: object) -> _FakeProviderResponse:
        """Record one chat-completions request and return a successful response."""
        self.requests.append({"url": url, **kwargs})
        return _FakeProviderResponse(self.content)


class MarkdownTranslatorTests(unittest.IsolatedAsyncioTestCase):
    """Verify concurrent, ordered, and structurally safe Markdown translation."""

    def _config(self, concurrency: int = 2) -> dict[str, object]:
        """Build a minimal lite translation configuration for tests."""
        return {
            "source_language": "en",
            "target_language": "ch",
            "lite": {"max_concurrency": concurrency},
            "llm_config": {},
        }

    async def test_consecutive_standalone_images_are_grouped_in_translated_markdown(self) -> None:
        """Write adjacent extracted images as compact rows in the final Markdown."""
        source = (
            "## Figure\n"
            "![a](images/a.png)\n"
            "![b](images/b.png)\n"
            "![c](images/c.png)\n"
            "![d](images/d.png)\n"
        )

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Return protected content unchanged to isolate layout post-processing."""
            return text

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            ).execute()
            translated = output.read_text(encoding="utf-8")

        rows = translated.splitlines()
        self.assertEqual(rows[0], "## Figure")
        self.assertEqual(rows[1].count("!["), 3)
        self.assertEqual(rows[2].count("!["), 1)
        self.assertEqual(translated.count("{width=0.32\\linewidth}"), 4)

    async def test_blocks_translate_concurrently_and_rebuild_in_original_order(self) -> None:
        """Limit concurrent requests while ordering output by original block index."""
        source = "## A\nbodyA\n## B\nbodyB"
        started: list[int] = []
        active = 0
        maximum_active = 0
        both_started = asyncio.Event()

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Complete blocks in reverse order after observing real concurrency."""
            nonlocal active, maximum_active
            started.append(block_index)
            active += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            await asyncio.sleep(0.01 * (2 - block_index))
            active -= 1
            return text.replace("body", "译文")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            ).execute()
            translated = output.read_text(encoding="utf-8")

        self.assertEqual(started, [0, 1])
        self.assertEqual(maximum_active, 2)
        self.assertEqual(translated, "## A\n译文A\n\n## B\n译文B")

    async def test_request_receives_glossary_and_protected_markdown(self) -> None:
        """Load project terms and restore protected structures after translation."""
        source = "## Method\nbody uses `code`, $x+y$, and [docs](https://example.test/a).\n"
        captured: dict[str, object] = {}

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Capture the protected request and translate only visible prose."""
            captured.update(text=text, glossary=glossary, block_index=block_index)
            return text.replace("Method", "方法").replace("body uses", "正文使用")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")
            write_project_terms_csv(output_dir / "project_terms.csv", {"body": "正文"})

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            ).execute()
            translated = output.read_text(encoding="utf-8")

        self.assertEqual(captured["glossary"], {"body": "正文"})
        self.assertEqual(captured["block_index"], 0)
        protected_text = str(captured["text"])
        self.assertNotIn("`code`", protected_text)
        self.assertNotIn("$x+y$", protected_text)
        self.assertNotIn("https://example.test/a", protected_text)
        self.assertEqual(
            translated,
            "## 方法\n正文使用 `code`, $x+y$, and [docs](https://example.test/a).\n",
        )

    async def test_provider_system_prompt_makes_glossary_priority_explicit(self) -> None:
        """Send the project glossary in the provider system message with strict priority."""
        source = "## Method\nbody\n"
        fake_session = _FakeProviderSession("## 方法\n正文\n")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")
            write_project_terms_csv(output_dir / "project_terms.csv", {"body": "正文"})
            config = self._config()
            config["llm_config"] = {
                "api_key": "test-key",
                "base_url": "https://provider.test/chat/completions",
                "model": "test-model",
            }

            with patch(
                "src.agents.tool_agents.markdown_translator_agent.aiohttp.ClientSession",
                return_value=fake_session,
            ):
                await MarkdownTranslatorAgent(
                    config,
                    source_path,
                    output_dir,
                    split_markdown(source),
                ).execute()

        request_payload = fake_session.requests[0]["json"]
        system_prompt = request_payload["messages"][0]["content"]
        self.assertIn("from English to Chinese", system_prompt)
        self.assertIn("[[LTP_<TYPE>_<N>]]", system_prompt)
        self.assertIn('"body": "正文"', system_prompt)
        self.assertIn("must take priority over all alternative translations", system_prompt)

    async def test_provider_system_prompt_requires_math_delimiters_for_symbols(self) -> None:
        """Bare symbols such as a lone Greek letter must come back as inline math."""
        source = "## Method\nbody\n"
        fake_session = _FakeProviderSession("## 方法\n正文\n")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")
            config = self._config()
            config["llm_config"] = {
                "api_key": "test-key",
                "base_url": "https://provider.test/chat/completions",
                "model": "test-model",
            }

            with patch(
                "src.agents.tool_agents.markdown_translator_agent.aiohttp.ClientSession",
                return_value=fake_session,
            ):
                await MarkdownTranslatorAgent(
                    config,
                    source_path,
                    output_dir,
                    split_markdown(source),
                ).execute()

        system_prompt = fake_session.requests[0]["json"]["messages"][0]["content"]
        self.assertIn("Keep every mathematical symbol inside math delimiters", system_prompt)
        self.assertIn("$\\rho$", system_prompt)
        self.assertIn("Do not wrap ordinary words in math delimiters", system_prompt)

    async def test_provider_preserves_trailing_markdown_line_breaks(self) -> None:
        """Do not trim line breaks needed to separate translated Markdown blocks."""
        fake_session = _FakeProviderSession("## 方法\n正文\n\n")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text("## Method\nbody\n", encoding="utf-8")
            config = self._config()
            config["llm_config"] = {
                "api_key": "test-key",
                "base_url": "https://provider.test/chat/completions",
                "model": "test-model",
            }
            agent = MarkdownTranslatorAgent(
                config,
                source_path,
                output_dir,
                split_markdown(source_path.read_text(encoding="utf-8")),
            )
            agent._session = fake_session

            translated = await agent._request_provider_translation("## Method\nbody\n", {}, 0)

        self.assertEqual(translated, "## 方法\n正文\n\n")

    async def test_translates_reference_heading_without_sending_or_changing_entries(self) -> None:
        """Translate a references heading while preserving its entries verbatim."""
        source = (
            "## Body\nbody\n\n"
            "## References\n\n"
            "[1] Ada Author. Original reference entry.\n\n"
            "## Appendix\nappendix\n"
        )
        requests: list[str] = []

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Capture exposed source text and translate only ordinary prose."""
            requests.append(text)
            return (
                text.replace("Body", "正文")
                .replace("body", "内容")
                .replace("References", "参考文献")
                .replace("Appendix", "附录")
                .replace("appendix", "附录正文")
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            ).execute()

            translated = output.read_text(encoding="utf-8")

        self.assertNotIn("Ada Author", requests[1])
        self.assertEqual(requests[1], "## References\n\n")
        self.assertEqual(
            translated,
            "## 正文\n内容\n\n"
            "## 参考文献\n\n"
            "[1] Ada Author. Original reference entry.\n\n"
            "## 附录\n附录正文\n",
        )

    async def test_reference_heading_keeps_a_blank_line_when_provider_trims_response(self) -> None:
        """Keep a blank line before preserved entries after a trimmed heading response."""
        source = "## References\n\n[1] Ada Author. Original reference entry.\n"

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Simulate a provider that removes trailing line breaks."""
            return text.replace("References", "参考文献").rstrip("\r\n")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            ).execute()

            translated = output.read_text(encoding="utf-8")

        self.assertEqual(translated, "## 参考文献\n\n[1] Ada Author. Original reference entry.\n")

    def test_concurrency_defaults_to_ten_and_rejects_invalid_values(self) -> None:
        """Use the lite default concurrency while rejecting unusable configuration."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text("body", encoding="utf-8")
            default_config = self._config()
            default_config["lite"] = {}
            self.assertEqual(
                MarkdownTranslatorAgent(default_config, source_path, output_dir, []).max_concurrency,
                10,
            )

            invalid_config = self._config()
            invalid_config["lite"] = {"max_concurrency": False}
            with self.assertRaisesRegex(ValueError, "positive integer"):
                MarkdownTranslatorAgent(invalid_config, source_path, output_dir, [])

    async def test_nontranslatable_and_protected_only_blocks_skip_requests(self) -> None:
        """Preserve explicitly disabled and protected-only blocks without LLM calls."""
        calls: list[int] = []
        blocks = [
            MarkdownBlock(index=0, text="```text\nsource code\n```\n"),
            MarkdownBlock(index=1, text="## Metadata\nkeep\n", translatable=False),
            MarkdownBlock(index=2, text="## Body\nbody\n"),
        ]

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Record which blocks were considered translatable."""
            calls.append(block_index)
            return text.replace("Body", "正文").replace("body", "内容")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text("".join(block.text for block in blocks), encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                self._config(),
                source_path,
                output_dir,
                blocks,
                request_translation=request,
            ).execute()
            translated = output.read_text(encoding="utf-8")

        self.assertEqual(calls, [2])
        self.assertEqual(
            translated,
            "```text\nsource code\n```\n\n## Metadata\nkeep\n\n## 正文\n内容\n",
        )

    async def test_retries_a_block_when_a_protected_token_is_missing(self) -> None:
        """Retry only the invalid block and write the result after a valid response."""
        calls: list[int] = []
        logs: list[tuple[str, str]] = []
        config = self._config()
        config["lite"] = {"max_concurrency": 1, "protected_token_retry_attempts": 1}
        config["_project_log_callback"] = lambda event: logs.append(
            (event["level"], event["message"])
        )

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Omit a protected token once before returning a valid translation."""
            calls.append(block_index)
            if len(calls) == 1:
                return re.sub(r"\[\[LTP_CODE_\d+\]\]", "", text, count=1)
            return text.replace("body", "正文")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text("## Method\nbody with `code`.\n", encoding="utf-8")

            output = await MarkdownTranslatorAgent(
                config,
                source_path,
                output_dir,
                split_markdown(source_path.read_text(encoding="utf-8")),
                request_translation=request,
            ).execute()

            self.assertEqual(
                output.read_text(encoding="utf-8"),
                "## Method\n正文 with `code`.\n",
            )

        self.assertEqual(calls, [0, 0])
        self.assertTrue(any(level == "warning" and "retrying" in message for level, message in logs))

    async def test_fails_after_protected_token_retry_budget_is_exhausted(self) -> None:
        """Keep output atomic after every response duplicates a protected token."""
        calls: list[int] = []
        config = self._config()
        config["lite"] = {"max_concurrency": 1, "protected_token_retry_attempts": 2}

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Return a response with a duplicated typed token on every attempt."""
            calls.append(block_index)
            token = re.search(r"\[\[LTP_CODE_\d+\]\]", text)
            self.assertIsNotNone(token)
            return text + str(token.group())

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source_path = output_dir / "source.md"
            source_path.write_text("## Method\nbody with `code`.\n", encoding="utf-8")
            agent = MarkdownTranslatorAgent(
                config,
                source_path,
                output_dir,
                split_markdown(source_path.read_text(encoding="utf-8")),
                request_translation=request,
            )

            with self.assertRaisesRegex(ValueError, "duplicated"):
                await agent.execute()

            self.assertFalse((output_dir / "translated.md").exists())
            self.assertFalse((output_dir / "translated.md.tmp").exists())

        self.assertEqual(calls, [0, 0, 0])

    async def test_failed_block_raises_and_does_not_write_output(self) -> None:
        """Raise provider failures and leave no partially translated artifact."""
        logs: list[tuple[str, str]] = []
        config = self._config()
        config["_project_log_callback"] = lambda event: logs.append(
            (event["level"], event["message"])
        )

        async def request(text: str, glossary: dict[str, str], block_index: int) -> str:
            """Fail one block to simulate an exhausted provider request."""
            if block_index == 0:
                raise RuntimeError("provider failed")
            return text

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            source = "## A\nbodyA\n## B\nbodyB"
            source_path = output_dir / "source.md"
            source_path.write_text(source, encoding="utf-8")
            agent = MarkdownTranslatorAgent(
                config,
                source_path,
                output_dir,
                split_markdown(source),
                request_translation=request,
            )

            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                await agent.execute()

            self.assertFalse((output_dir / "translated.md").exists())
            self.assertFalse((output_dir / "translated.md.tmp").exists())

        self.assertTrue(any(level == "error" and "failed" in message.lower() for level, message in logs))


if __name__ == "__main__":
    unittest.main()
