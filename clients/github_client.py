"""Async GitHub REST API client for fetching repository trees and file contents."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from config import Settings
from models.schemas import RepoFile
from utils.file_filter import is_excluded, score_file

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """Raised when a GitHub API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GitHubClient:
    """Fetches repository metadata and file contents via the GitHub REST API."""

    def __init__(self, settings: Settings) -> None:
        self._base = settings.github_api_base
        self._timeout = settings.github_timeout
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._headers = headers

    async def fetch_repo_files(self, owner: str, repo: str) -> list[RepoFile]:
        """Return a scored, filtered list of files in the repository.

        Uses the Git Trees API with ``recursive=1`` for a single-call
        listing of the entire tree.
        """
        url = f"{self._base}/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout
        ) as client:
            resp = await client.get(url)

        if resp.status_code == 404:
            raise GitHubClientError(
                f"Repository {owner}/{repo} not found or is private", status_code=404
            )
        if resp.status_code == 403:
            raise GitHubClientError(
                "GitHub API rate limit exceeded. Set GITHUB_TOKEN to increase limits.",
                status_code=403,
            )
        if resp.status_code != 200:
            raise GitHubClientError(
                f"GitHub API error: {resp.status_code}", status_code=resp.status_code
            )

        data: dict[str, Any] = resp.json()
        tree: list[dict[str, Any]] = data.get("tree", [])

        files: list[RepoFile] = []
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item["path"]
            size = item.get("size", 0)
            if is_excluded(path, size):
                continue
            files.append(RepoFile(path=path, size=size, score=score_file(path)))

        files.sort(key=lambda f: f.score)
        logger.info(
            "Filtered %d / %d tree entries for %s/%s",
            len(files),
            len(tree),
            owner,
            repo,
        )
        return files

    async def download_files(
        self,
        owner: str,
        repo: str,
        files: list[RepoFile],
        budget: int,
        per_file_max: int,
    ) -> list[RepoFile]:
        """Download file contents in priority order, stopping at *budget* chars.

        Downloads are batched concurrently (up to 10 at a time) and stop
        early once the character budget is consumed.
        """
        used = 0
        batch_size = 10
        result: list[RepoFile] = []

        async with httpx.AsyncClient(
            headers=self._headers, timeout=self._timeout
        ) as client:
            for i in range(0, len(files), batch_size):
                if used >= budget:
                    break
                batch = files[i : i + batch_size]
                tasks = [self._fetch_raw(client, owner, repo, f.path) for f in batch]
                contents = await asyncio.gather(*tasks, return_exceptions=True)

                for f, content in zip(batch, contents):
                    if isinstance(content, BaseException):
                        logger.warning("Failed to download %s: %s", f.path, content)
                        continue
                    if content is None:
                        continue
                    f.content = content
                    result.append(f)
                    used += min(len(content), per_file_max)
                    if used >= budget:
                        break

        logger.info(
            "Downloaded %d files (~%d chars) for %s/%s", len(result), used, owner, repo
        )
        return result

    async def _fetch_raw(
        self, client: httpx.AsyncClient, owner: str, repo: str, path: str
    ) -> str | None:
        """Fetch raw file content. Returns None on non-200 or decode errors."""
        url = f"{self._base}/repos/{owner}/{repo}/contents/{path}"
        resp = await client.get(
            url, headers={"Accept": "application/vnd.github.v3.raw"}
        )
        if resp.status_code != 200:
            return None
        try:
            return resp.text
        except Exception:
            return None
