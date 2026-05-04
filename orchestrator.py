from __future__ import annotations

import asyncio
import time
from typing import Any

from agents import AgentSystem
from config import Settings
from diff_processor import DiffProcessor
from github_client import GitHubClient
from models import AgentCategory, ChangedFile, Finding, ReviewResult, ReviewStats

AGENT_TYPES: tuple[AgentCategory, ...] = ("security", "performance", "quality")


class CodeReviewOrchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        github_client: GitHubClient | None = None,
        diff_processor: DiffProcessor | None = None,
        agent_system: AgentSystem | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.github_client = github_client or GitHubClient(self.settings)
        self.diff_processor = diff_processor or DiffProcessor(self.settings)
        self.agent_system = agent_system or AgentSystem(self.settings)

    async def review_pr(self, repo_name: str, pr_number: int, post_comment: bool | None = None) -> ReviewResult:
        changed_files = self.github_client.get_pr_diff(repo_name, pr_number)
        review = await self.review_changed_files(changed_files)
        should_post = self.settings.post_github_comment if post_comment is None else post_comment
        if should_post:
            try:
                self.github_client.post_inline_review(repo_name, pr_number, review)
                review.comment_posted = True
            except RuntimeError as exc:
                review.comment_error = str(exc)
                review.comment_posted = False
        return review

    async def review_changed_files(self, changed_files: list[ChangedFile | dict[str, Any]]) -> ReviewResult:
        started_at = time.perf_counter()
        chunks = self.diff_processor.process_changed_files(changed_files)
        starting_tokens = self.agent_system.total_tokens
        findings_by_agent: dict[AgentCategory, list[Finding]] = {agent: [] for agent in AGENT_TYPES}

        tasks = [self._review_with_agent(chunk, agent) for chunk in chunks for agent in AGENT_TYPES]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    continue
                agent, findings = result
                findings_by_agent[agent].extend(findings)

        review = await self.agent_system.synthesize(findings_by_agent)
        elapsed = time.perf_counter() - started_at
        review.stats = ReviewStats(
            files_reviewed=len({chunk.file_path for chunk in chunks}),
            chunks_reviewed=len(chunks),
            lines_added=sum(self._file_additions(file) for file in changed_files),
            lines_deleted=sum(self._file_deletions(file) for file in changed_files),
            tokens_estimated=sum(chunk.token_estimate for chunk in chunks) + (self.agent_system.total_tokens - starting_tokens),
            model=self.settings.hf_model_id,
            cost_per_1k_tokens=self.settings.cost_per_1k_tokens,
            elapsed_seconds=elapsed,
        )
        return review

    async def _review_with_agent(self, chunk: Any, agent: AgentCategory) -> tuple[AgentCategory, list[Finding]]:
        try:
            return agent, await self.agent_system.review_chunk(chunk, agent)
        except Exception:
            return agent, []

    def _file_additions(self, changed_file: ChangedFile | dict[str, Any]) -> int:
        if isinstance(changed_file, ChangedFile):
            return changed_file.additions
        return int(changed_file.get("additions", 0) or 0)

    def _file_deletions(self, changed_file: ChangedFile | dict[str, Any]) -> int:
        if isinstance(changed_file, ChangedFile):
            return changed_file.deletions
        return int(changed_file.get("deletions", 0) or 0)
