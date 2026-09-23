"""Asynchronous Markdown block translation for the lite engine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

import aiohttp

from src.agents.tool_agents.base_tool_agent import BaseToolAgent
from src.config import merge_llm_payload, parse_custom_json
from src.engines.lite_markdown import (
    MarkdownBlock,
    ProtectedMarkdown,
    ProtectedTokenValidationError,
    group_standalone_images,
    protect_markdown,
    rebuild_markdown,
    restore_markdown,
)
from src.formats.latex.prompts import language_label
from src.terminology import load_term_csv, merge_term_pairs, project_terms_path


TranslationRequest = Callable[[str, dict[str, str], int], Awaitable[str]]
_PROVIDER_ATTEMPTS = 3
_PROVIDER_RETRY_DELAY = 5
_PROVIDER_TIMEOUT = 100
_PROTECTED_TOKEN_RETRY_ATTEMPTS = 2


class MarkdownTranslatorAgent(BaseToolAgent):
    """Translate protected Markdown blocks concurrently and rebuild them in order."""

    def __init__(
        self,
        config: dict[str, Any],
        source_markdown: Path,
        output_dir: Path,
        blocks: Sequence[MarkdownBlock],
        request_translation: TranslationRequest | None = None,
    ) -> None:
        """Initialize paths, ordered blocks, provider settings, and test injection."""
        super().__init__(agent_name="MarkdownTranslatorAgent", config=config)
        self.source_markdown = Path(source_markdown)
        self.output_dir = Path(output_dir)
        self.blocks = tuple(blocks)
        self._request_translation_callback = request_translation
        self._session: aiohttp.ClientSession | None = None

        llm_config = config.get("llm_config") or {}
        self.model = llm_config.get("model", "gpt-4o")
        self.base_url = llm_config.get("base_url") or "https://api.openai.com/v1/chat/completions"
        self.api_key = llm_config.get("api_key")
        self.custom_json = parse_custom_json(llm_config.get("custom_json"))
        self.source_language = config.get("source_language", "en")
        self.target_language = config.get("target_language", "ch")
        self.max_concurrency = self._configured_concurrency(config)
        self.protected_token_retry_attempts = (
            self._configured_protected_token_retry_attempts(config)
        )

    async def execute(self) -> Path:
        """Translate every eligible block and atomically write ``translated.md``."""
        project_name = self.output_dir.name
        self.log(f"Starting Markdown translation for project: {project_name}.")
        temporary_path = self.output_dir / "translated.md.tmp"
        output_path = self.output_dir / "translated.md"
        try:
            glossary = self._load_glossary()
            self.log(f"Loaded {len(glossary)} glossary entries for Markdown translation.")
            self.log(
                f"Translating {len(self.blocks)} Markdown blocks with concurrency "
                f"limit {self.max_concurrency}."
            )
            if self._request_translation_callback is None:
                timeout = aiohttp.ClientTimeout(total=_PROVIDER_TIMEOUT)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    self._session = session
                    translated_blocks = await self._translate_all_blocks(glossary)
                    self._session = None
            else:
                translated_blocks = await self._translate_all_blocks(glossary)

            translated_markdown = group_standalone_images(
                rebuild_markdown(translated_blocks)
            )
            self.output_dir.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(translated_markdown, encoding="utf-8")
            temporary_path.replace(output_path)
            self.log(
                f"Successfully translated Markdown for {project_name}: {output_path}."
            )
            return output_path
        except Exception as exc:
            self._session = None
            if temporary_path.exists():
                temporary_path.unlink()
            self.log(
                f"Markdown translation failed for {project_name}: {exc}",
                level="error",
            )
            raise

    async def request_translation(
        self,
        text: str,
        glossary: dict[str, str],
        block_index: int,
        protected_token_retry: bool = False,
    ) -> str:
        """Invoke the injected callback or the configured chat-completions provider."""
        if self._request_translation_callback is not None:
            return await self._request_translation_callback(text, glossary, block_index)
        return await self._request_provider_translation(
            text,
            glossary,
            block_index,
            protected_token_retry=protected_token_retry,
        )

    async def _translate_all_blocks(
        self, glossary: dict[str, str]
    ) -> list[MarkdownBlock]:
        """Run block tasks with a semaphore and cancel siblings after failure."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [
            asyncio.create_task(self._translate_block(block, glossary, semaphore))
            for block in self.blocks
        ]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _translate_block(
        self,
        block: MarkdownBlock,
        glossary: dict[str, str],
        semaphore: asyncio.Semaphore,
    ) -> MarkdownBlock:
        """Protect, translate, and restore one eligible Markdown block."""
        if not block.translatable:
            self.log(f"Skipping non-translatable Markdown block {block.index}.", level="debug")
            return block

        translation_text = block.text
        if block.preserved_suffix:
            translation_text = block.text[: -len(block.preserved_suffix)]
        protected = protect_markdown(translation_text)
        if not self._has_translatable_text(protected):
            self.log(f"Skipping protected-only Markdown block {block.index}.", level="debug")
            return block

        max_attempts = self.protected_token_retry_attempts + 1
        for attempt in range(1, max_attempts + 1):
            async with semaphore:
                self.log(f"Translating Markdown block {block.index}.", level="debug")
                translated = await self.request_translation(
                    protected.text,
                    glossary,
                    block.index,
                    protected_token_retry=attempt > 1,
                )
            if not isinstance(translated, str):
                raise TypeError(
                    f"Markdown translation for block {block.index} must return a string"
                )
            try:
                restored = restore_markdown(translated, protected)
            except ProtectedTokenValidationError as exc:
                if attempt >= max_attempts:
                    raise
                self.log(
                    f"Markdown block {block.index} protected token validation failed "
                    f"on attempt {attempt}/{max_attempts} "
                    f"({len(exc.missing_tokens)} missing, "
                    f"{len(exc.duplicate_tokens)} duplicated); retrying.",
                    level="warning",
                )
                continue
            if block.preserved_suffix:
                trailing_newlines = len(restored) - len(restored.rstrip("\r\n"))
                if trailing_newlines < 2:
                    restored += "\n" * (2 - trailing_newlines)
            restored += block.preserved_suffix
            self.log(f"Translated Markdown block {block.index}.", level="debug")
            return MarkdownBlock(
                index=block.index,
                text=restored,
                translatable=block.translatable,
                preserved_suffix=block.preserved_suffix,
            )
        raise RuntimeError("protected token retry loop exhausted")

    async def _request_provider_translation(
        self,
        text: str,
        glossary: dict[str, str],
        block_index: int,
        protected_token_retry: bool = False,
    ) -> str:
        """Request one Markdown translation with bounded transport retries."""
        if not self.api_key:
            raise RuntimeError("llm_config.api_key is required for Markdown translation")
        if self._session is None:
            raise RuntimeError("Markdown translation provider session is not initialized")

        source_label = language_label(self.source_language)
        target_label = language_label(self.target_language)
        system_prompt = (
            f"Translate academic Markdown from {source_label} to {target_label}. "
            "Preserve every protected token matching [[LTP_<TYPE>_<N>]] exactly "
            "once and in place. "
            "Preserve Markdown headings, paragraph boundaries, blank lines, and line breaks. "
            "Never translate, reorder, or reformat formulas. Keep every mathematical "
            "symbol inside math delimiters: when the source prose contains a bare "
            "symbol such as a lone Greek letter (for example \u03c1), emit it as inline "
            "math ($\\rho$) so the PDF can render the glyph. Do not wrap ordinary "
            "words in math delimiters. "
            "Return only the translated Markdown without code fences or commentary."
        )
        if glossary:
            system_prompt += (
                " Use the following glossary consistently. Glossary entries must take "
                "priority over all alternative translations:\n<Glossary>\n"
                f"{json.dumps(glossary, ensure_ascii=False)}"
            )
        user_content = text
        if protected_token_retry:
            user_content = (
                "The previous response failed protected-token validation. Translate "
                "the Markdown below again from scratch. Every token in the form "
                "[[LTP_<TYPE>_<N>]] that appears in the Markdown must occur exactly "
                "once in the response. Return only the translated Markdown.\n\n"
                f"{text}"
            )
        payload = merge_llm_payload(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.7,
                "max_new_tokens": 8192,
            },
            self.custom_json,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(1, _PROVIDER_ATTEMPTS + 1):
            try:
                async with self._session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=_PROVIDER_TIMEOUT,
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return str(result["choices"][0]["message"]["content"])
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                self.log(
                    f"Markdown block {block_index} provider attempt "
                    f"{attempt}/{_PROVIDER_ATTEMPTS} failed: {exc}",
                    level="warning",
                )
                if attempt >= _PROVIDER_ATTEMPTS:
                    raise
                await asyncio.sleep(_PROVIDER_RETRY_DELAY)
        raise RuntimeError("Markdown translation provider retry loop exhausted")

    def _load_glossary(self) -> dict[str, str]:
        """Load user and project terms with existing first-source precedence."""
        user_terms: dict[str, str] = {}
        project_terms: dict[str, str] = {}
        user_term = self.config.get("user_term")
        if user_term:
            user_result = load_term_csv(
                Path(str(user_term)), source_language=str(self.source_language)
            )
            user_terms = user_result.terms
            for warning in user_result.warnings:
                self.log(warning, level="warning")

        terms_path = project_terms_path(self.output_dir)
        if terms_path.is_file():
            project_result = load_term_csv(
                terms_path, source_language=str(self.source_language)
            )
            project_terms = project_result.terms
            for warning in project_result.warnings:
                self.log(warning, level="warning")

        return merge_term_pairs(
            user_terms.items(),
            project_terms.items(),
            source_language=str(self.source_language),
        )

    @staticmethod
    def _configured_concurrency(config: dict[str, Any]) -> int:
        """Read a positive lite translation concurrency or return the default ten."""
        lite_config = config.get("lite") or {}
        value = lite_config.get("max_concurrency", 10) if isinstance(lite_config, dict) else 10
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("lite.max_concurrency must be a positive integer")
        return value

    @staticmethod
    def _configured_protected_token_retry_attempts(config: dict[str, Any]) -> int:
        """Read a non-negative extra retry count for invalid protected tokens."""
        lite_config = config.get("lite") or {}
        nested_value = (
            lite_config.get("protected_token_retry_attempts", _PROTECTED_TOKEN_RETRY_ATTEMPTS)
            if isinstance(lite_config, dict)
            else _PROTECTED_TOKEN_RETRY_ATTEMPTS
        )
        value = config.get("protected_token_retry_attempts", nested_value)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                "lite.protected_token_retry_attempts must be a non-negative integer"
            )
        return value

    @staticmethod
    def _has_translatable_text(protected: ProtectedMarkdown) -> bool:
        """Return whether protected Markdown still contains letters or digits."""
        visible = protected.text
        for token in protected.tokens:
            visible = visible.replace(token, "")
        return any(character.isalnum() for character in visible)
