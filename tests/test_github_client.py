from __future__ import annotations

import hashlib
import hmac

from config import Settings
from github_client import GitHubClient
from models import Finding, ReviewResult, ReviewStats


def test_webhook_signature_verification() -> None:
    settings = Settings(github_webhook_secret="secret", mock_ai=True)
    client = GitHubClient(settings)
    payload = b'{"ok":true}'
    signature = "sha256=" + hmac.new(b"secret", payload, hashlib.sha256).hexdigest()

    assert client.verify_webhook_signature(payload, signature)
    assert not client.verify_webhook_signature(payload, "sha256=bad")


def test_webhook_pr_context_includes_installation_id() -> None:
    client = GitHubClient(Settings(mock_ai=True))
    payload = {
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {"number": 42, "draft": False},
        "installation": {"id": 123456},
    }

    assert client.webhook_pr_context(payload) == ("owner/repo", 42, 123456)


def test_github_app_private_key_normalizes_escaped_newlines() -> None:
    client = GitHubClient(Settings(github_app_private_key="line1\\nline2", mock_ai=True))

    assert client._github_app_private_key() == "line1\nline2"


def test_format_review_comment_contains_findings_and_stats() -> None:
    client = GitHubClient(Settings(mock_ai=True))
    review = ReviewResult(
        summary="Found one issue.",
        high_count=1,
        findings=[Finding("app.py", 7, "high", "security", "Issue", "Fix", 0.9)],
        stats=ReviewStats(files_reviewed=1, chunks_reviewed=1, lines_added=3, lines_deleted=1, tokens_estimated=1000),
    )

    body = client.format_review_comment(review)

    assert "## Walkthrough" in body
    assert "`app.py`" in body
    assert "**Cost:**" in body
