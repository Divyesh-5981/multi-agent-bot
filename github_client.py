from __future__ import annotations

import hashlib
import hmac
from typing import Any

from config import Settings
from models import ChangedFile, ReviewResult, SEVERITIES, SEVERITY_RANK

SEVERITY_TITLES = {
    "critical": "Critical Issues",
    "high": "High Priority",
    "medium": "Medium Priority",
    "low": "Low Priority",
}

SEVERITY_EMOJIS = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
}


class GitHubClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.client = self._build_client(self.settings.github_token) if self.settings.github_token else None

    def get_pr_diff(self, repo_name: str, pr_number: int) -> list[ChangedFile]:
        if not self.client:
            raise RuntimeError("GITHUB_TOKEN is required to fetch pull request diffs")
        repo = self.client.get_repo(repo_name)
        pull_request = repo.get_pull(pr_number)
        changed_files: list[ChangedFile] = []
        for changed_file in pull_request.get_files():
            changed_files.append(
                ChangedFile(
                    filename=changed_file.filename,
                    patch=changed_file.patch,
                    additions=changed_file.additions,
                    deletions=changed_file.deletions,
                    status=changed_file.status,
                )
            )
        return changed_files

    def post_review_comment(self, repo_name: str, pr_number: int, review: ReviewResult) -> str:
        if not self.client:
            raise RuntimeError("GITHUB_TOKEN is required to post pull request comments")
        repo = self.client.get_repo(repo_name)
        pull_request = repo.get_pull(pr_number)
        body = self.format_review_comment(review)
        try:
            pull_request.create_issue_comment(body)
        except Exception as exc:
            raise RuntimeError(f"Failed to post GitHub comment: {exc}") from exc
        return body

    def _build_client(self, token: str | None):
        if not token:
            return None
        try:
            from github import Github
        except ImportError as exc:
            raise RuntimeError("PyGithub is required when GITHUB_TOKEN is configured. Run `pip install -r requirements.txt`.") from exc
        return Github(token)

    def verify_webhook_signature(self, payload_body: bytes, signature_header: str | None) -> bool:
        secret = self.settings.github_webhook_secret
        if not secret:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def format_review_comment(self, review: ReviewResult) -> str:
        stats = review.stats
        lines = [
            "## 🤖 AI Code Review",
            f"*Reviewed by 4x `{stats.model}` agents in {stats.elapsed_seconds:.1f}s*",
            "",
            "### 📊 Summary",
            review.summary,
            "",
            "---",
            "",
        ]

        if not review.findings:
            lines.extend(
                [
                    "### ✅ No blocking issues found",
                    "The Security, Performance, and Code Quality agents did not identify actionable issues in the reviewed diff chunks.",
                    "",
                    "---",
                    "",
                ]
            )
        else:
            sorted_findings = sorted(
                review.findings,
                key=lambda finding: (-SEVERITY_RANK[finding.severity], finding.file, finding.line, finding.category),
            )
            for severity in SEVERITIES:
                severity_findings = [finding for finding in sorted_findings if finding.severity == severity]
                if not severity_findings:
                    continue
                lines.extend(
                    [
                        f"### {SEVERITY_EMOJIS[severity]} {SEVERITY_TITLES[severity]} ({len(severity_findings)})",
                        "",
                    ]
                )
                for finding in severity_findings:
                    confidence = f" · confidence {finding.confidence:.0%}" if finding.confidence is not None else ""
                    lines.extend(
                        [
                            f"**`{finding.file}:{finding.line}`** - {finding.category.title()}{confidence}",
                            f"❌ **Issue:** {finding.issue}",
                            f"💡 **Fix:** {finding.suggestion}",
                            "",
                        ]
                    )
                lines.extend(["---", ""])

        lines.extend(
            [
                "### ✅ What Went Well",
                "- The review was split into focused Security, Performance, and Code Quality passes.",
                "- Findings were deduplicated and prioritized before this summary was posted.",
                "",
                "<details>",
                "<summary>📈 Review Stats</summary>",
                "",
                f"- **Files reviewed:** {stats.files_reviewed}",
                f"- **Chunks reviewed:** {stats.chunks_reviewed}",
                f"- **Lines changed:** +{stats.lines_added} / -{stats.lines_deleted}",
                "- **Agents used:** Security, Performance, Quality, Synthesizer",
                f"- **Model:** `{stats.model}`",
                f"- **Estimated tokens:** {stats.tokens_estimated:,}",
                f"- **Estimated cost:** ${stats.estimated_cost:.4f}",
                f"- **Review time:** {stats.elapsed_seconds:.1f}s",
                "",
                "</details>",
            ]
        )
        return "\n".join(lines)

    def webhook_pr_context(self, payload: dict[str, Any]) -> tuple[str, int] | None:
        action = payload.get("action")
        if action not in {"opened", "reopened", "synchronize", "ready_for_review"}:
            return None
        pull_request = payload.get("pull_request") or {}
        if pull_request.get("draft"):
            return None
        repository = payload.get("repository") or {}
        repo_name = repository.get("full_name")
        pr_number = pull_request.get("number") or payload.get("number")
        if not repo_name or not pr_number:
            return None
        return str(repo_name), int(pr_number)
