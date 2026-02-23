from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class SummarizeRequest(BaseModel):
    github_url: str = Field(
        ...,
        description="Full GitHub repository URL",
        examples=["https://github.com/owner/repo"],
    )

    @field_validator("github_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        pattern = r"^https?://github\.com/[\w\-\.]+/[\w\-\.]+/?$"
        if not re.match(pattern, v.rstrip("/")):
            raise ValueError(
                "Invalid GitHub URL. Expected format: https://github.com/owner/repo"
            )
        return v.rstrip("/")

    def parse_owner_repo(self) -> tuple[str, str]:
        parts = self.github_url.rstrip("/").split("/")
        return parts[-2], parts[-1]


class SummarizeResponse(BaseModel):
    summary: str
    technologies: list[str]
    structure: str


class RepoFile(BaseModel):
    """Internal model representing a scored repository file."""

    path: str
    size: int
    score: float = 0.0
    content: str | None = None
