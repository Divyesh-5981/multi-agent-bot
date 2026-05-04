from __future__ import annotations

import hashlib
import hmac
from typing import Any

from config import Settings
from models import ChangedFile, Finding, ReviewResult, SEVERITY_RANK

SEVERITY_LABELS = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
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

    def post_inline_review(self, repo_name: str, pr_number: int, review: ReviewResult) -> None:
        """Post a proper pull request review with inline comments on specific lines."""
        if not self.client:
            raise RuntimeError("GITHUB_TOKEN is required to post pull request reviews")

        repo = self.client.get_repo(repo_name)
        pull_request = repo.get_pull(pr_number)
        head_commit = pull_request.get_commits().reversed[0]

        # Build the set of valid diff lines per file so we only comment on reviewable lines
        valid_lines = self._get_valid_diff_lines(pull_request)

        # Build inline comments from findings
        inline_comments = []
        for finding in review.findings:
            line = finding.line
            file_lines = valid_lines.get(finding.file, set())

            # Only comment on lines that exist in the diff; skip otherwise
            if line not in file_lines:
                nearest = self._nearest_valid_line(line, file_lines)
                if nearest is None:
                    continue
                line = nearest

            body = self._format_inline_comment(finding)
            inline_comments.append({"path": finding.file, "line": line, "body": body})

        # Deduplicate: one comment per file:line, merge findings
        deduped = self._deduplicate_inline_comments(inline_comments)

        # Decide the review verdict
        event, verdict_summary = self._decide_verdict(review)

        # Build the review body
        review_body = self._format_review_body(review, verdict_summary)

        try:
            pull_request.create_review(
                commit=head_commit,
                body=review_body,
                event=event,
                comments=[
                    {"path": c["path"], "line": c["line"], "body": c["body"]}
                    for c in deduped
                ],
            )
        except Exception as exc:
            error_msg = str(exc)
            # GitHub doesn't allow REQUEST_CHANGES on your own PR — fall back to COMMENT
            if "422" in error_msg and "own pull request" in error_msg and event == "REQUEST_CHANGES":
                pull_request.create_review(
                    commit=head_commit,
                    body=review_body,
                    event="COMMENT",
                    comments=[
                        {"path": c["path"], "line": c["line"], "body": c["body"]}
                        for c in deduped
                    ],
                )
                return
            if "403" in error_msg or "Resource not accessible" in error_msg:
                raise RuntimeError(
                    "GitHub token lacks pull request review permission. "
                    "Update your fine-grained token at https://github.com/settings/tokens "
                    "and grant 'Pull requests: Read and write' for this repository."
                ) from exc
            raise RuntimeError(f"Failed to post review: {exc}") from exc

    def _get_valid_diff_lines(self, pull_request: Any) -> dict[str, set[int]]:
        """Parse the PR diff to find which new-file line numbers are valid for inline comments."""
        import re
        hunk_re = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
        valid: dict[str, set[int]] = {}
        for f in pull_request.get_files():
            if not f.patch:
                continue
            lines: set[int] = set()
            current_line = 0
            for raw_line in f.patch.splitlines():
                m = hunk_re.match(raw_line)
                if m:
                    current_line = int(m.group(1))
                    continue
                if raw_line.startswith("-"):
                    continue
                if raw_line.startswith("+"):
                    lines.add(current_line)
                    current_line += 1
                else:
                    current_line += 1
            valid[f.filename] = lines
        return valid

    def _nearest_valid_line(self, target: int, valid_lines: set[int]) -> int | None:
        if not valid_lines:
            return None
        return min(valid_lines, key=lambda l: abs(l - target))

    def _decide_verdict(self, review: ReviewResult) -> tuple[str, str]:
        """Decide whether to approve or request changes based on findings."""
        if review.critical_count > 0:
            return "REQUEST_CHANGES", (
                f"Requesting changes. Found {review.critical_count} critical issue(s) "
                "that must be resolved before this PR can be merged."
            )
        if review.high_count > 0:
            return "REQUEST_CHANGES", (
                f"Requesting changes. Found {review.high_count} high-severity issue(s) "
                "that should be addressed before merging."
            )
        if review.medium_count > 0 or review.low_count > 0:
            total = review.medium_count + review.low_count
            return "COMMENT", (
                f"No blocking issues found. {total} minor suggestion(s) noted inline. "
                "This PR can be merged at the author's discretion."
            )
        return "APPROVE", "No issues found. The changes look clean across security, performance, and code quality checks."

    def _format_inline_comment(self, finding: Finding) -> str:
        """Format a single inline comment like a senior engineer would write it."""
        label = SEVERITY_LABELS[finding.severity]
        category = finding.category.title()
        lines = [
            f"**[{label}] {category}**",
            "",
            finding.issue,
            "",
            f"**Suggestion:** {finding.suggestion}",
        ]
        return "\n".join(lines)

    def _deduplicate_inline_comments(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge multiple comments on the same file:line into one."""
        grouped: dict[tuple[str, int], list[str]] = {}
        for c in comments:
            key = (c["path"], c["line"])
            grouped.setdefault(key, []).append(c["body"])
        result = []
        for (path, line), bodies in grouped.items():
            if len(bodies) == 1:
                result.append({"path": path, "line": line, "body": bodies[0]})
            else:
                merged = "\n\n---\n\n".join(bodies)
                result.append({"path": path, "line": line, "body": merged})
        return result

    def _format_review_body(self, review: ReviewResult, verdict: str) -> str:
        """Format the top-level review summary body."""
        stats = review.stats
        lines = [
            "## AI Code Review",
            "",
            f"Reviewed by multi-agent system (`{stats.model}`) in {stats.elapsed_seconds:.1f}s.",
            "",
            "### Verdict",
            "",
            verdict,
            "",
            "### Summary",
            "",
            review.summary,
            "",
        ]

        counts = []
        if review.critical_count:
            counts.append(f"{review.critical_count} critical")
        if review.high_count:
            counts.append(f"{review.high_count} high")
        if review.medium_count:
            counts.append(f"{review.medium_count} medium")
        if review.low_count:
            counts.append(f"{review.low_count} low")

        if counts:
            lines.append(f"**Issues found:** {', '.join(counts)}")
        else:
            lines.append("**Issues found:** None")

        lines.extend([
            "",
            "<details>",
            "<summary>Review Stats</summary>",
            "",
            f"- Files reviewed: {stats.files_reviewed}",
            f"- Chunks reviewed: {stats.chunks_reviewed}",
            f"- Lines changed: +{stats.lines_added} / -{stats.lines_deleted}",
            f"- Agents: Security, Performance, Quality, Synthesizer",
            f"- Model: `{stats.model}`",
            f"- Estimated tokens: {stats.tokens_estimated:,}",
            f"- Estimated cost: ${stats.estimated_cost:.4f}",
            f"- Review time: {stats.elapsed_seconds:.1f}s",
            "",
            "</details>",
        ])
        return "\n".join(lines)

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
        """Legacy summary comment format — kept for /review/local endpoint."""
        return self._format_review_body(review, self._decide_verdict(review)[1])

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
