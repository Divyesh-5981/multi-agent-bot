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
    description="Multi-agent system reviews pull request diffs for security, performance, and code quality issues.",
    version="1.0.0",
)


class LocalReviewRequest(BaseModel):
    files: list[dict[str, Any]] = Field(..., description="Changed files using filename, patch, additions, and deletions fields")
    post_comment: bool = False


class PullRequestReviewRequest(BaseModel):
    repo_name: str = Field(..., examples=["owner/repo"])
    pr_number: int = Field(..., ge=1)
    post_comment: bool | None = None
    installation_id: int | None = Field(default=None, ge=1)


@app.get("/")
def root() -> dict[str, Any]:
    auth_mode = "github_app" if settings.github_app_configured else ("pat" if settings.github_token else "none")
    return {
        "status": "running",
        "model": settings.hf_model_id,
        "agents": ["security", "performance", "quality", "synthesizer"],
        "github_configured": settings.github_configured,
        "github_auth_mode": auth_mode,
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
    print(f"[WEBHOOK] Received {request.method} {request.url.path} ({len(body)} bytes)")
    print(f"[WEBHOOK] Signature header present: {x_hub_signature_256 is not None}")
    print(f"[WEBHOOK] X-GitHub-Event: {request.headers.get('x-github-event', 'N/A')}")

    if not orchestrator.github_client.verify_webhook_signature(body, x_hub_signature_256):
        print("[WEBHOOK] ❌ Signature verification FAILED")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    print("[WEBHOOK] ✅ Signature verified")

    payload = await request.json()
    action = payload.get("action", "N/A")
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})
    print(f"[WEBHOOK] Action: {action}")
    print(f"[WEBHOOK] Repo: {repo.get('full_name', 'N/A')}")
    print(f"[WEBHOOK] PR: #{pr.get('number', 'N/A')} - {pr.get('title', 'N/A')}")
    print(f"[WEBHOOK] PR draft: {pr.get('draft', 'N/A')}")
    print(f"[WEBHOOK] Installation ID: {installation.get('id', 'N/A')}")

    context = orchestrator.github_client.webhook_pr_context(payload)
    if context is None:
        print(f"[WEBHOOK] ⏭️ Ignored (action={action}, draft={pr.get('draft')})")
        return JSONResponse({"status": "ignored"})

    repo_name, pr_number, installation_id = context
    print(f"[WEBHOOK] 🚀 Processing review for {repo_name}#{pr_number} (installation={installation_id})")
    background_tasks.add_task(_run_pr_review_background, repo_name, pr_number, installation_id)
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
        installation_id=request.installation_id,
    )
    return review.to_dict()


@app.post("/review/local")
async def review_local(request: LocalReviewRequest) -> dict[str, Any]:
    review = await orchestrator.review_changed_files(request.files)
    return review.to_dict()


async def _run_pr_review_background(repo_name: str, pr_number: int, installation_id: int | None = None) -> None:
    print(f"[REVIEW] Starting background review for {repo_name}#{pr_number} (installation={installation_id})")
    try:
        review = await orchestrator.review_pr(repo_name, pr_number, post_comment=True, installation_id=installation_id)
        print(f"[REVIEW] ✅ Review complete for {repo_name}#{pr_number}")
        print(f"[REVIEW]   Summary: {review.summary[:100]}...")
        print(f"[REVIEW]   Findings: {len(review.findings)} total")
        print(f"[REVIEW]   Comment posted: {review.comment_posted}")
        if review.comment_error:
            print(f"[REVIEW]   Comment error: {review.comment_error}")
    except Exception as exc:
        import traceback
        print(f"[REVIEW] ❌ Review failed for {repo_name}#{pr_number}: {exc}")
        traceback.print_exc()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
