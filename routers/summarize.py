"""POST /summarize endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from clients.github_client import GitHubClient, GitHubClientError
from clients.llm_client import LLMClient, LLMClientError
from config import Settings, get_settings
from models.schemas import SummarizeRequest, SummarizeResponse
from services.summarizer import SummarizerService

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_service(settings: Settings = Depends(get_settings)) -> SummarizerService:
    return SummarizerService(
        github_client=GitHubClient(settings),
        llm_client=LLMClient(settings),
        settings=settings,
    )


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_repo(
    body: SummarizeRequest,
    service: SummarizerService = Depends(_build_service),
) -> SummarizeResponse:
    owner, repo = body.parse_owner_repo()
    try:
        return await service.summarize(owner, repo)
    except GitHubClientError as exc:
        status = exc.status_code or 502
        if status == 404:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if status == 403:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMClientError as exc:
        logger.error("LLM error: %s", exc)
        raise HTTPException(
            status_code=502, detail=f"LLM service error: {exc}"
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error during summarization")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
