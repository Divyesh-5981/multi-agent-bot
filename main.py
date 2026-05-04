from __future__ import annotations

import asyncio
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import Settings
from orchestrator import CodeReviewOrchestrator

settings = Settings.from_env()
orchestrator = CodeReviewOrchestrator(settings=settings)
app = FastAPI(
    title="Multi-Agent Code Review Bot",
    description="Four Gemma 3 1B agents review pull request diffs for security, performance, and code quality issues.",
    version="1.0.0",
)


class LocalReviewRequest(BaseModel):
    files: list[dict[str, Any]] = Field(..., description="Changed files using filename, patch, additions, and deletions fields")
    post_comment: bool = False


class PullRequestReviewRequest(BaseModel):
    repo_name: str = Field(..., examples=["owner/repo"])
    pr_number: int = Field(..., ge=1)
    post_comment: bool | None = None


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "status": "running",
        "model": settings.hf_model_id,
        "agents": ["security", "performance", "quality", "synthesizer"],
        "github_configured": settings.github_configured,
        "hf_configured": settings.hf_configured,
        "mock_ai": settings.mock_ai,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


async def _handle_webhook_request(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = None,
) -> JSONResponse:
    body = await request.body()
    if not orchestrator.github_client.verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    payload = await request.json()
    context = orchestrator.github_client.webhook_pr_context(payload)
    if context is None:
        return JSONResponse({"status": "ignored"})

    repo_name, pr_number = context
    background_tasks.add_task(_run_pr_review_background, repo_name, pr_number)
    return JSONResponse({"status": "processing", "repo": repo_name, "pr_number": pr_number})


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> JSONResponse:
    return await _handle_webhook_request(request, background_tasks, x_hub_signature_256)


@app.post("/")
async def handle_webhook_root(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> JSONResponse:
    """Fallback webhook handler — ngrok free tier can strip the path."""
    return await _handle_webhook_request(request, background_tasks, x_hub_signature_256)


@app.post("/review/pr")
async def review_pr(request: PullRequestReviewRequest) -> dict[str, Any]:
    review = await orchestrator.review_pr(
        repo_name=request.repo_name,
        pr_number=request.pr_number,
        post_comment=request.post_comment,
    )
    return review.to_dict()


@app.post("/review/local")
async def review_local(request: LocalReviewRequest) -> dict[str, Any]:
    review = await orchestrator.review_changed_files(request.files)
    return review.to_dict()


async def _run_pr_review_background(repo_name: str, pr_number: int) -> None:
    try:
        await orchestrator.review_pr(repo_name, pr_number, post_comment=True)
    except Exception as exc:
        print(f"Review failed for {repo_name}#{pr_number}: {exc}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
