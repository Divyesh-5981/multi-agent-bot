from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from typing import Any

import aiohttp

from config import Settings
from models import AgentCategory, DiffChunk, Finding, ReviewResult, SEVERITY_RANK, count_findings, normalize_severity

SECURITY_AGENT_PROMPT = """You are a security-focused code reviewer. Analyze ONLY security issues.

Review this code change and identify:
- SQL injection risks
- XSS vulnerabilities
- Hardcoded secrets/credentials
- Insecure authentication
- Unsafe deserialization
- Path traversal risks

Language: {language}
File: {file_path}
Line numbers are shown before each changed line. Use those exact new-file line numbers.

CHANGED CODE:
{code_diff}

Output ONLY valid JSON:
{{
  "findings": [
    {{
      "line": <line_number>,
      "severity": "critical|high|medium|low",
      "issue": "<brief issue>",
      "suggestion": "<how to fix>",
      "confidence": <number_between_0_and_1>
    }}
  ]
}}

If no security issues found, return: {{"findings": []}}
"""

PERFORMANCE_AGENT_PROMPT = """You are a performance optimization expert. Analyze ONLY performance issues.

Review this code change and identify:
- N+1 database queries
- Inefficient loops (O(n²) or worse)
- Missing indexes/caching
- Unnecessary API calls
- Memory leaks
- Blocking operations in async code

Language: {language}
File: {file_path}
Line numbers are shown before each changed line. Use those exact new-file line numbers.

CHANGED CODE:
{code_diff}

Output ONLY valid JSON:
{{
  "findings": [
    {{
      "line": <line_number>,
      "severity": "high|medium|low",
      "issue": "<brief issue>",
      "suggestion": "<optimization strategy>",
      "confidence": <number_between_0_and_1>
    }}
  ]
}}

If no performance issues found, return: {{"findings": []}}
"""

QUALITY_AGENT_PROMPT = """You are a code quality expert. Analyze ONLY code quality issues.

Review this code change and identify:
- Missing error handling
- Poor naming conventions
- Code duplication
- Missing input validation
- Overly complex functions (>20 lines)
- Missing comments for complex logic

Language: {language}
File: {file_path}
Line numbers are shown before each changed line. Use those exact new-file line numbers.

CHANGED CODE:
{code_diff}

Output ONLY valid JSON:
{{
  "findings": [
    {{
      "line": <line_number>,
      "severity": "medium|low",
      "issue": "<brief issue>",
      "suggestion": "<improvement>",
      "confidence": <number_between_0_and_1>
    }}
  ]
}}

If no quality issues found, return: {{"findings": []}}
"""

SYNTHESIZER_AGENT_PROMPT = """You are consolidating code review findings from 3 specialist reviewers.

SECURITY FINDINGS:
{security_findings}

PERFORMANCE FINDINGS:
{performance_findings}

QUALITY FINDINGS:
{quality_findings}

Tasks:
1. Remove duplicate issues (same line, similar issue)
2. Resolve conflicts by keeping the higher severity
3. Group by file and severity
4. Create a friendly two-sentence summary

Output ONLY valid JSON:
{{
  "summary": "<2-sentence overview>",
  "critical_count": <number>,
  "high_count": <number>,
  "medium_count": <number>,
  "low_count": <number>,
  "findings": [
    {{
      "file": "<file_path>",
      "line": <line_number>,
      "severity": "critical|high|medium|low",
      "category": "security|performance|quality",
      "issue": "<issue>",
      "suggestion": "<fix>",
      "confidence": <number_between_0_and_1>
    }}
  ]
}}
"""

PROMPTS: dict[AgentCategory, str] = {
    "security": SECURITY_AGENT_PROMPT,
    "performance": PERFORMANCE_AGENT_PROMPT,
    "quality": QUALITY_AGENT_PROMPT,
}

JSON_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


class AgentSystem:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.total_tokens = 0
        self._semaphore = asyncio.Semaphore(self.settings.max_agent_concurrency)

    async def review_chunk(self, chunk: DiffChunk, agent_type: AgentCategory) -> list[Finding]:
        if self.settings.mock_ai:
            return self._mock_review_chunk(chunk, agent_type)

        prompt = self.build_prompt(agent_type, chunk)
        response = await self.call_gemma(prompt)
        parsed = self.parse_findings(response)
        return [self._normalize_finding(item, chunk, agent_type) for item in parsed]

    def build_prompt(self, agent_type: AgentCategory, chunk: DiffChunk) -> str:
        return PROMPTS[agent_type].format(
            language=chunk.language,
            file_path=chunk.file_path,
            code_diff=chunk.patch,
        )

    async def call_gemma(self, prompt: str) -> str:
        if not self.settings.hf_api_token:
            raise RuntimeError("HF_API_TOKEN is required unless MOCK_AI=true")

        # Unique request ID prevents response caching on free-tier APIs
        import uuid
        request_id = str(uuid.uuid4())[:8]

        payload = {
            "model": self.settings.hf_model_id,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a code review assistant. Always respond with valid JSON only. No markdown, no explanation, just JSON.",
                },
                {"role": "user", "content": f"[rid:{request_id}]\n{prompt}"},
            ],
            "max_tokens": 1500,
            "temperature": 0.15,
            "top_p": 0.9,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.hf_api_token}",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=self.settings.agent_timeout_seconds)

        async with self._semaphore:
            for attempt in range(1, self.settings.agent_max_retries + 1):
                try:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(self.settings.hf_api_url, headers=headers, json=payload) as response:
                            body = await response.text()
                            if response.status in {429, 500, 502, 503, 504} and attempt < self.settings.agent_max_retries:
                                await asyncio.sleep(min(2**attempt, 8))
                                continue
                            if response.status >= 400:
                                raise RuntimeError(f"Hugging Face API error {response.status}: {body[:500]}")
                            self.total_tokens += self.estimate_tokens(prompt)
                            data = json.loads(body)
                            return self._extract_chat_response(data)
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
                    if attempt >= self.settings.agent_max_retries:
                        raise RuntimeError(f"API request failed after {attempt} attempts: {exc}") from exc
                    await asyncio.sleep(min(2**attempt, 8))

        raise RuntimeError("API request failed")

    def parse_findings(self, response: str) -> list[dict[str, Any]]:
        data = self._safe_json_parse(response)
        findings = data.get("findings", []) if isinstance(data, dict) else []
        return findings if isinstance(findings, list) else []

    async def synthesize(self, findings_by_agent: dict[AgentCategory, list[Finding]]) -> ReviewResult:
        deterministic = self._deterministic_synthesis(findings_by_agent)
        if self.settings.mock_ai or not self.settings.hf_api_token or not deterministic.findings:
            return deterministic

        prompt = SYNTHESIZER_AGENT_PROMPT.format(
            security_findings=json.dumps([finding.to_dict() for finding in findings_by_agent.get("security", [])]),
            performance_findings=json.dumps([finding.to_dict() for finding in findings_by_agent.get("performance", [])]),
            quality_findings=json.dumps([finding.to_dict() for finding in findings_by_agent.get("quality", [])]),
        )

        try:
            response = await self.call_gemma(prompt)
            data = self._safe_json_parse(response)
            if not isinstance(data, dict):
                return deterministic
            model_findings = data.get("findings", [])
            if not isinstance(model_findings, list):
                return deterministic
            normalized = [self._normalize_synthesized_finding(item) for item in model_findings]
            normalized = [finding for finding in normalized if finding is not None]
            if not normalized:
                return deterministic
            counts = count_findings(normalized)
            return ReviewResult(
                summary=str(data.get("summary") or self._build_summary(normalized)),
                critical_count=counts["critical"],
                high_count=counts["high"],
                medium_count=counts["medium"],
                low_count=counts["low"],
                findings=normalized,
                stats=deterministic.stats,
            )
        except Exception:
            return deterministic

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _deterministic_synthesis(self, findings_by_agent: dict[AgentCategory, list[Finding]]) -> ReviewResult:
        deduped: dict[tuple[str, int, str], Finding] = {}
        for finding in self._flatten_findings(findings_by_agent):
            key = (finding.file, finding.line, self._issue_key(finding.issue))
            existing = deduped.get(key)
            if not existing or SEVERITY_RANK[finding.severity] > SEVERITY_RANK[existing.severity]:
                deduped[key] = finding

        findings = sorted(
            deduped.values(),
            key=lambda item: (-SEVERITY_RANK[item.severity], item.file, item.line, item.category),
        )
        counts = count_findings(findings)
        return ReviewResult(
            summary=self._build_summary(findings),
            critical_count=counts["critical"],
            high_count=counts["high"],
            medium_count=counts["medium"],
            low_count=counts["low"],
            findings=findings,
        )

    def _flatten_findings(self, findings_by_agent: dict[AgentCategory, list[Finding]]) -> Iterable[Finding]:
        for findings in findings_by_agent.values():
            yield from findings

    def _normalize_finding(self, item: dict[str, Any], chunk: DiffChunk, category: AgentCategory) -> Finding:
        requested_line = self._safe_int(item.get("line"), chunk.start_line)
        line = requested_line if chunk.contains_line(requested_line) else chunk.nearest_line(requested_line)
        return Finding(
            file=chunk.file_path,
            line=line,
            severity=normalize_severity(item.get("severity"), "medium" if category != "security" else "low"),
            category=category,
            issue=str(item.get("issue") or "Potential issue detected").strip(),
            suggestion=str(item.get("suggestion") or "Review this change manually.").strip(),
            confidence=self._safe_confidence(item.get("confidence")),
            source_agent=category,
        )

    def _normalize_synthesized_finding(self, item: Any) -> Finding | None:
        if not isinstance(item, dict):
            return None
        category = str(item.get("category") or "quality").lower()
        if category not in PROMPTS:
            category = "quality"
        return Finding(
            file=str(item.get("file") or item.get("file_path") or "unknown"),
            line=self._safe_int(item.get("line"), 1),
            severity=normalize_severity(item.get("severity"), "low"),
            category=category,  # type: ignore[arg-type]
            issue=str(item.get("issue") or "Potential issue detected").strip(),
            suggestion=str(item.get("suggestion") or "Review this change manually.").strip(),
            confidence=self._safe_confidence(item.get("confidence")),
            source_agent="synthesizer",
        )

    def _safe_json_parse(self, response: str) -> Any:
        stripped = response.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        block_match = JSON_CODE_BLOCK_RE.search(stripped)
        if block_match:
            try:
                return json.loads(block_match.group(1))
            except json.JSONDecodeError:
                pass

        object_text = self._extract_first_json_object(stripped)
        if object_text:
            return json.loads(object_text)
        return {}

    def _extract_first_json_object(self, text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    def _extract_chat_response(self, payload: Any) -> str:
        """Extract content from OpenAI-compatible chat completions response."""
        if isinstance(payload, dict):
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if content:
                    return str(content)
            # Update token count from usage if available
            usage = payload.get("usage")
            if isinstance(usage, dict):
                total = usage.get("total_tokens", 0)
                if total:
                    self.total_tokens += total
        # Fallback to legacy extraction
        return self._extract_generated_text(payload)

    def _extract_generated_text(self, payload: Any) -> str:
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                return str(first.get("generated_text") or first.get("summary_text") or first)
            return str(first)
        if isinstance(payload, dict):
            if "generated_text" in payload:
                return str(payload["generated_text"])
            if "error" in payload:
                raise RuntimeError(str(payload["error"]))
            return str(payload)
        return str(payload)

    def _build_summary(self, findings: list[Finding]) -> str:
        if not findings:
            return "No critical issues found. The reviewed changes look good from the security, performance, and quality checks."
        counts = count_findings(findings)
        affected_files = len({finding.file for finding in findings})
        count_parts = [f"{counts[severity]} {severity}" for severity in ("critical", "high", "medium", "low") if counts[severity]]
        return f"Found {', '.join(count_parts)} issue(s) across {affected_files} file(s). Review the prioritized findings below before merging."

    def _issue_key(self, issue: str) -> str:
        words = re.findall(r"[a-z0-9]+", issue.lower())
        return " ".join(words[:8])

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_confidence(self, value: Any) -> float | None:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, confidence))

    def _mock_review_chunk(self, chunk: DiffChunk, agent_type: AgentCategory) -> list[Finding]:
        added_lines = [line for line in chunk.lines if line.kind == "added"]
        if agent_type == "security":
            return self._mock_security_findings(chunk, added_lines)
        if agent_type == "performance":
            return self._mock_performance_findings(chunk, added_lines)
        return self._mock_quality_findings(chunk, added_lines)

    def _mock_security_findings(self, chunk: DiffChunk, added_lines: list[Any]) -> list[Finding]:
        findings: list[Finding] = []
        secret_pattern = re.compile(r"(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}", re.IGNORECASE)
        for line in added_lines:
            lowered = line.content.lower()
            if re.search(r"select\s+.*\+|f['\"].*select\s+|execute\([^)]*\+", line.content, re.IGNORECASE):
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "critical", "security", "Possible SQL injection from string-built query", "Use parameterized queries or your ORM query builder bindings.", 0.82, "security"))
            elif "innerhtml" in lowered or "dangerouslysetinnerhtml" in lowered:
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "high", "security", "Potential XSS sink uses raw HTML assignment", "Sanitize trusted HTML or render text content instead of raw HTML.", 0.78, "security"))
            elif "eval(" in lowered or "exec(" in lowered:
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "high", "security", "Dynamic code execution can execute attacker-controlled input", "Remove dynamic execution or strictly validate against an allowlist.", 0.8, "security"))
            elif "../" in line.content and ("open(" in lowered or "readfile" in lowered or "path" in lowered):
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "medium", "security", "Potential path traversal with user-controlled path", "Normalize paths and enforce access within an approved base directory.", 0.7, "security"))
            elif secret_pattern.search(line.content):
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "critical", "security", "Hardcoded credential-like value in source", "Move secrets to environment variables or a managed secrets store.", 0.86, "security"))
        return findings

    def _mock_performance_findings(self, chunk: DiffChunk, added_lines: list[Any]) -> list[Finding]:
        findings: list[Finding] = []
        loop_depth = 0
        for line in added_lines:
            stripped = line.content.strip()
            lowered = stripped.lower()
            if re.match(r"(for|while)\b", stripped):
                loop_depth += 1
            if loop_depth and any(token in lowered for token in ("requests.", "fetch(", "axios.", ".get(", ".filter(", ".find(")):
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "medium", "performance", "Potential repeated expensive operation inside a loop", "Batch the work, cache repeated lookups, or move the operation outside the loop.", 0.66, "performance"))
            if loop_depth >= 2:
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "medium", "performance", "Nested loop may become O(n²) on large inputs", "Use a map/set index or pre-group data to avoid quadratic scans.", 0.64, "performance"))
                loop_depth = 0
        return findings[:3]

    def _mock_quality_findings(self, chunk: DiffChunk, added_lines: list[Any]) -> list[Finding]:
        findings: list[Finding] = []
        added_text = "\n".join(line.content for line in added_lines)
        if len(added_lines) > 25 and "try" not in added_text.lower() and chunk.language in {"Python", "JavaScript", "TypeScript"}:
            findings.append(Finding(chunk.file_path, added_lines[0].new_line or chunk.start_line, "low", "quality", "Large new block has no explicit error handling", "Add focused error handling around IO, network, parsing, or database operations.", 0.58, "quality"))
        for line in added_lines:
            if re.search(r"\b(todo|fixme)\b", line.content, re.IGNORECASE):
                findings.append(Finding(chunk.file_path, line.new_line or chunk.start_line, "low", "quality", "TODO/FIXME left in changed code", "Resolve the TODO before merge or link it to a tracked follow-up issue.", 0.74, "quality"))
        return findings[:3]
