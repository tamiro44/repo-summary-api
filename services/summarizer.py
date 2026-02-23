"""Core orchestration service that ties GitHub fetching, context building, and LLM summarization together."""

from __future__ import annotations

import hashlib
import logging
import time
from functools import lru_cache
from typing import Any

from clients.github_client import GitHubClient
from clients.llm_client import LLMClient
from config import Settings
from models.schemas import SummarizeResponse
from utils.context_builder import build_context

logger = logging.getLogger(__name__)

# Simple in-memory LRU cache keyed by repo URL.
_cache: dict[str, SummarizeResponse] = {}
_cache_order: list[str] = []


def _cache_get(key: str) -> SummarizeResponse | None:
    return _cache.get(key)


def _cache_set(key: str, value: SummarizeResponse, max_size: int) -> None:
    if key in _cache:
        return
    if len(_cache) >= max_size:
        oldest = _cache_order.pop(0)
        _cache.pop(oldest, None)
    _cache[key] = value
    _cache_order.append(key)


class SummarizerService:
    """Orchestrates the full summarization pipeline."""

    def __init__(
        self,
        github_client: GitHubClient,
        llm_client: LLMClient,
        settings: Settings,
    ) -> None:
        self._gh = github_client
        self._llm = llm_client
        self._settings = settings

    async def summarize(self, owner: str, repo: str) -> SummarizeResponse:
        cache_key = f"{owner}/{repo}"
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Cache hit for %s", cache_key)
            return cached

        t0 = time.monotonic()

        # 1. Fetch and score repository tree
        files = await self._gh.fetch_repo_files(owner, repo)
        logger.info(
            "[%s] Tree fetched: %d candidate files (%.1fs)",
            cache_key,
            len(files),
            time.monotonic() - t0,
        )

        # 2. Download file contents within budget
        budget = self._settings.content_budget
        per_file_max = self._settings.per_file_max_chars
        files = await self._gh.download_files(owner, repo, files, budget, per_file_max)
        logger.info("[%s] Files downloaded (%.1fs)", cache_key, time.monotonic() - t0)

        # 3. Build LLM context
        context = build_context(files, budget, per_file_max)
        logger.info(
            "[%s] Context built: %d chars (%.1fs)",
            cache_key,
            len(context),
            time.monotonic() - t0,
        )

        # 4. Call LLM
        raw: dict[str, Any] = await self._llm.summarize(context)
        logger.info(
            "[%s] LLM response received (%.1fs)", cache_key, time.monotonic() - t0
        )

        response = SummarizeResponse(
            summary=raw.get("summary", ""),
            technologies=raw.get("technologies", []),
            structure=raw.get("structure", ""),
        )

        _cache_set(cache_key, response, self._settings.cache_max_size)
        logger.info("[%s] Total time: %.2fs", cache_key, time.monotonic() - t0)
        return response
