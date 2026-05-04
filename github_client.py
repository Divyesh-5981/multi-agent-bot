from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any

from config import Settings
from models import ChangedFile, Finding, ReviewResult, SEVERITY_RANK

SEVERITY_ICONS = {
    "critical": "\U0001f534",  # red circle
    "high": "\U0001f7e0",      # orange circle
    "medium": "\U0001f7e1",    # yellow circle
    "low": "\U0001f535",       # blue circle
}

CATEGORY_LABELS = {
    "security": "Security",
    "performance": "Performance",
    "quality": "Code Quality",
}


class GitHubClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.client = self._build_client(self.settings.github_token) if self.settings.github_token else None

    # ── PR diff fetching ──────────────────────────────────────────────

    def get_pr_diff(self, repo_name: str, pr_number: int, installation_id: int | None = None) -> list[ChangedFile]:
        client = self._authenticated_client(installation_id)
        if not client:
            raise RuntimeError(
                "GitHub authentication is required to fetch pull request diffs. "
                "Configure a GitHub App installation or GITHUB_TOKEN."
            )
        repo = client.get_repo(repo_name)
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

    # ── Inline review posting ─────────────────────────────────────────

    def post_inline_review(
        self,
        repo_name: str,
        pr_number: int,
        review: ReviewResult,
        installation_id: int | None = None,
    ) -> None:
        """Post a pull request review with inline comments on specific diff lines."""
        client = self._authenticated_client(installation_id)
        if not client:
            raise RuntimeError(
                "GitHub authentication is required to post pull request reviews. "
                "Configure a GitHub App installation or GITHUB_TOKEN."
            )

        repo = client.get_repo(repo_name)
        pull_request = repo.get_pull(pr_number)
        head_commit = pull_request.get_commits().reversed[0]

        valid_lines = self._get_valid_diff_lines(pull_request)

        inline_comments = []
        for finding in review.findings:
            line = finding.line
            file_lines = valid_lines.get(finding.file, set())

            if line not in file_lines:
                nearest = self._nearest_valid_line(line, file_lines)
                if nearest is None:
                    continue
                line = nearest

            body = self._format_inline_comment(finding)
            inline_comments.append({"path": finding.file, "line": line, "body": body})

        deduped = self._deduplicate_inline_comments(inline_comments)
        event, verdict_text = self._decide_verdict(review)
        review_body = self._format_review_body(review, verdict_text)

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
            if "422" in error_msg and "own pull request" in error_msg and event in ("REQUEST_CHANGES", "APPROVE"):
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
                    "GitHub credentials lack pull request review permission. "
                    "Grant 'Pull requests: Read and write' and 'Contents: Read' for this repository."
                ) from exc
            raise RuntimeError(f"Failed to post review: {exc}") from exc

    # ── Review body (walkthrough) ─────────────────────────────────────

    def _format_review_body(self, review: ReviewResult, verdict: str) -> str:
        stats = review.stats
        total_issues = len(review.findings)

        lines: list[str] = []

        # Header
        lines.append("## Walkthrough")
        lines.append("")
        lines.append(review.summary)
        lines.append("")

        # Verdict
        lines.append(f"> **Verdict:** {verdict}")
        lines.append("")

        # Severity breakdown table
        if total_issues > 0:
            lines.append("### Issues")
            lines.append("")
            lines.append("| Severity | Count |")
            lines.append("|----------|------:|")
            if review.critical_count:
                lines.append(f"| {SEVERITY_ICONS['critical']} Critical | {review.critical_count} |")
            if review.high_count:
                lines.append(f"| {SEVERITY_ICONS['high']} Major | {review.high_count} |")
            if review.medium_count:
                lines.append(f"| {SEVERITY_ICONS['medium']} Minor | {review.medium_count} |")
            if review.low_count:
                lines.append(f"| {SEVERITY_ICONS['low']} Trivial | {review.low_count} |")
            lines.append("")

        # Changed files table
        files_with_issues: dict[str, list[Finding]] = {}
        for f in review.findings:
            files_with_issues.setdefault(f.file, []).append(f)

        if files_with_issues:
            lines.append("### Files reviewed")
            lines.append("")
            lines.append("| File | Issues | Categories |")
            lines.append("|------|-------:|------------|")
            for filepath in sorted(files_with_issues):
                findings = files_with_issues[filepath]
                categories = sorted({CATEGORY_LABELS.get(f.category, f.category) for f in findings})
                max_sev = max(findings, key=lambda f: SEVERITY_RANK[f.severity])
                icon = SEVERITY_ICONS[max_sev.severity]
                lines.append(f"| `{filepath}` | {icon} {len(findings)} | {', '.join(categories)} |")
            lines.append("")

        # Collapsible stats
        lines.append("<details>")
        lines.append("<summary>Review details</summary>")
        lines.append("")
        lines.append(f"**Model:** `{stats.model}`")
        lines.append(f"**Files reviewed:** {stats.files_reviewed} &nbsp;|&nbsp; "
                      f"**Chunks:** {stats.chunks_reviewed} &nbsp;|&nbsp; "
                      f"**Lines changed:** +{stats.lines_added} / -{stats.lines_deleted}")
        lines.append(f"**Tokens:** ~{stats.tokens_estimated:,} &nbsp;|&nbsp; "
                      f"**Cost:** ${stats.estimated_cost:.4f} &nbsp;|&nbsp; "
                      f"**Time:** {stats.elapsed_seconds:.1f}s")
        lines.append(f"**Agents:** Security, Performance, Quality, Synthesizer")
        lines.append("")
        lines.append("</details>")

        return "\n".join(lines)

    # ── Inline comment formatting ─────────────────────────────────────

    def _format_inline_comment(self, finding: Finding) -> str:
        icon = SEVERITY_ICONS[finding.severity]
        severity = finding.severity.capitalize()
        category = CATEGORY_LABELS.get(finding.category, finding.category)

        lines = [
            f"{icon} **{severity}** &mdash; {category}",
            "",
            finding.issue,
            "",
            f"> **Suggestion:** {finding.suggestion}",
        ]
        return "\n".join(lines)

    def _deduplicate_inline_comments(self, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
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

    # ── Verdict logic ─────────────────────────────────────────────────

    def _decide_verdict(self, review: ReviewResult) -> tuple[str, str]:
        if review.critical_count > 0:
            return "REQUEST_CHANGES", (
                f"Changes requested — {review.critical_count} critical issue(s) "
                "must be resolved before merging."
            )
        if review.high_count > 0:
            return "REQUEST_CHANGES", (
                f"Changes requested — {review.high_count} major issue(s) "
                "should be addressed before merging."
            )
        if review.medium_count > 0 or review.low_count > 0:
            total = review.medium_count + review.low_count
            return "COMMENT", (
                f"Approved with comments — {total} suggestion(s) noted inline. "
                "Safe to merge at the author's discretion."
            )
        return "APPROVE", (
            "Looks good — no issues found across security, performance, "
            "and code quality checks."
        )

    # ── Diff line validation ──────────────────────────────────────────

    def _get_valid_diff_lines(self, pull_request: Any) -> dict[str, set[int]]:
        import re
        hunk_re = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
        valid: dict[str, set[int]] = {}
        for f in pull_request.get_files():
            if not f.patch:
                continue
            file_lines: set[int] = set()
            current_line = 0
            for raw_line in f.patch.splitlines():
                m = hunk_re.match(raw_line)
                if m:
                    current_line = int(m.group(1))
                    continue
                if raw_line.startswith("-"):
                    continue
                if raw_line.startswith("+"):
                    file_lines.add(current_line)
                    current_line += 1
                else:
                    current_line += 1
            valid[f.filename] = file_lines
        return valid

    def _nearest_valid_line(self, target: int, valid_lines: set[int]) -> int | None:
        if not valid_lines:
            return None
        return min(valid_lines, key=lambda l: abs(l - target))

    # ── Legacy / utility ──────────────────────────────────────────────

    def format_review_comment(self, review: ReviewResult) -> str:
        """Legacy summary format for /review/local endpoint."""
        return self._format_review_body(review, self._decide_verdict(review)[1])

    def _build_client(self, token: str | None):
        if not token:
            return None
        try:
            from github import Github
        except ImportError as exc:
            raise RuntimeError(
                "PyGithub is required when GITHUB_TOKEN is configured. "
                "Run `pip install -r requirements.txt`."
            ) from exc
        return Github(token)

    def _authenticated_client(self, installation_id: int | None = None):
        effective_installation_id = installation_id or self.settings.github_app_installation_id
        if effective_installation_id is not None:
            if not self.settings.github_app_configured:
                raise RuntimeError(
                    "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH "
                    "are required to authenticate as a GitHub App installation."
                )
            return self._build_app_installation_client(effective_installation_id)
        if self.client:
            return self.client
        if self.settings.github_app_configured:
            raise RuntimeError(
                "GitHub App installation id is required. Use webhook payload installation.id "
                "or set GITHUB_APP_INSTALLATION_ID for manual runs."
            )
        return None

    def _build_app_installation_client(self, installation_id: int):
        try:
            from github import Auth, Github, GithubIntegration
        except ImportError as exc:
            raise RuntimeError(
                "PyGithub is required when GitHub App authentication is configured. "
                "Run `pip install -r requirements.txt`."
            ) from exc
        private_key = self._github_app_private_key()
        if not self.settings.github_app_id or not private_key:
            raise RuntimeError(
                "GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY or GITHUB_APP_PRIVATE_KEY_PATH "
                "are required to authenticate as a GitHub App installation."
            )
        app_auth = Auth.AppAuth(self.settings.github_app_id, private_key)
        integration = GithubIntegration(auth=app_auth)
        access_token = integration.get_access_token(installation_id)
        return Github(auth=Auth.Token(access_token.token))

    def _github_app_private_key(self) -> str | None:
        if self.settings.github_app_private_key:
            return self.settings.github_app_private_key.replace("\\n", "\n")
        if self.settings.github_app_private_key_path:
            return Path(self.settings.github_app_private_key_path).read_text(encoding="utf-8")
        return None

    def verify_webhook_signature(self, payload_body: bytes, signature_header: str | None) -> bool:
        secret = self.settings.github_webhook_secret
        if not secret:
            return True
        if not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def webhook_pr_context(self, payload: dict[str, Any]) -> tuple[str, int, int | None] | None:
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
        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        return str(repo_name), int(pr_number), int(installation_id) if installation_id else None
