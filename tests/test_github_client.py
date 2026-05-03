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


def test_format_review_comment_contains_findings_and_stats() -> None:
    client = GitHubClient(Settings(mock_ai=True))
    review = ReviewResult(
        summary="Found one issue.",
        high_count=1,
        findings=[Finding("app.py", 7, "high", "security", "Issue", "Fix", 0.9)],
        stats=ReviewStats(files_reviewed=1, chunks_reviewed=1, lines_added=3, lines_deleted=1, tokens_estimated=1000),
    )

    body = client.format_review_comment(review)

    assert "AI Code Review" in body
    assert "app.py:7" in body
    assert "Estimated cost" in body
