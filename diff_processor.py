from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from config import Settings
from models import ChangedFile, DiffChunk, DiffLine

HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
)

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript JSX",
    ".ts": "TypeScript",
    ".tsx": "TypeScript JSX",
    ".java": "Java",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".c": "C",
    ".cs": "C#",
    ".rs": "Rust",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
}

SKIP_EXTENSIONS = {
    ".7z",
    ".avif",
    ".bmp",
    ".class",
    ".dll",
    ".doc",
    ".docx",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lock",
    ".min.js",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".so",
    ".svg",
    ".tar",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}

SKIP_FILENAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "go.sum",
}

SKIP_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
}

PRIORITY_LANGUAGES = {"Python", "JavaScript", "JavaScript JSX", "TypeScript", "TypeScript JSX", "Go", "Java"}


class DiffProcessor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()

    def process_changed_files(self, changed_files: Iterable[ChangedFile | dict[str, Any]]) -> list[DiffChunk]:
        chunks: list[DiffChunk] = []
        for changed_file in changed_files:
            file_data = self._coerce_changed_file(changed_file)
            if not self.should_review(file_data.filename) or not file_data.patch:
                continue
            chunks.extend(self.chunk_file(file_data))
        return self.prioritize_chunks(chunks)

    def chunk_file(self, changed_file: ChangedFile) -> list[DiffChunk]:
        language = self.detect_language(changed_file.filename)
        chunks: list[DiffChunk] = []
        current_header: str | None = None
        current_lines: list[DiffLine] = []
        old_line = 0
        new_line = 0

        def flush_current() -> None:
            if current_header and current_lines:
                chunks.extend(self._split_hunk(changed_file.filename, language, current_header, current_lines))

        for raw_line in changed_file.patch.splitlines():
            header_match = HUNK_HEADER_RE.match(raw_line)
            if header_match:
                flush_current()
                current_header = raw_line
                current_lines = []
                old_line = int(header_match.group("old_start"))
                new_line = int(header_match.group("new_start"))
                continue

            if not current_header or self._is_diff_metadata(raw_line):
                continue

            if raw_line.startswith("\\ No newline"):
                continue

            marker = raw_line[:1]
            content = raw_line[1:] if marker in {" ", "+", "-"} else raw_line

            if marker == "+":
                current_lines.append(DiffLine(kind="added", content=content, new_line=new_line))
                new_line += 1
            elif marker == "-":
                current_lines.append(DiffLine(kind="removed", content=content, old_line=old_line))
                old_line += 1
            else:
                current_lines.append(DiffLine(kind="context", content=content, old_line=old_line, new_line=new_line))
                old_line += 1
                new_line += 1

        flush_current()
        return chunks

    def prioritize_chunks(self, chunks: list[DiffChunk]) -> list[DiffChunk]:
        if len(chunks) <= self.settings.max_review_chunks:
            return chunks

        def priority(chunk: DiffChunk) -> tuple[int, int, int]:
            language_priority = 0 if chunk.language in PRIORITY_LANGUAGES else 1
            has_additions = 0 if chunk.additions > 0 else 1
            return language_priority, has_additions, -chunk.additions

        return sorted(chunks, key=priority)[: self.settings.max_review_chunks]

    def should_review(self, filename: str) -> bool:
        normalized = filename.replace("\\", "/").lower()
        path = PurePosixPath(normalized)
        if any(part in SKIP_PATH_PARTS for part in path.parts):
            return False
        if path.name in SKIP_FILENAMES:
            return False
        if normalized.endswith(".min.js"):
            return False
        return path.suffix not in SKIP_EXTENSIONS

    def detect_language(self, filename: str) -> str:
        normalized = filename.lower()
        if normalized.endswith(".min.js"):
            return "Generated JavaScript"
        suffix = PurePosixPath(normalized).suffix
        return LANGUAGE_BY_EXTENSION.get(suffix, "Unknown")

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _split_hunk(self, file_path: str, language: str, header: str, lines: list[DiffLine]) -> list[DiffChunk]:
        chunks: list[DiffChunk] = []
        current_lines: list[DiffLine] = []

        for line in lines:
            candidate = [*current_lines, line]
            candidate_patch = self._format_patch(header, candidate)
            if current_lines and self.estimate_tokens(candidate_patch) > self.settings.max_tokens_per_chunk:
                chunks.append(self._make_chunk(file_path, language, header, current_lines))
                current_lines = [line]
            else:
                current_lines = candidate

        if current_lines:
            chunks.append(self._make_chunk(file_path, language, header, current_lines))
        return chunks

    def _make_chunk(self, file_path: str, language: str, header: str, lines: list[DiffLine]) -> DiffChunk:
        new_line_numbers = [line.new_line for line in lines if line.new_line is not None]
        start_line = min(new_line_numbers) if new_line_numbers else 1
        end_line = max(new_line_numbers) if new_line_numbers else start_line
        patch = self._format_patch(header, lines)
        return DiffChunk(
            file_path=file_path,
            language=language,
            start_line=start_line,
            end_line=end_line,
            patch=patch,
            lines=list(lines),
            additions=sum(1 for line in lines if line.kind == "added"),
            deletions=sum(1 for line in lines if line.kind == "removed"),
            token_estimate=self.estimate_tokens(patch),
        )

    def _format_patch(self, header: str, lines: list[DiffLine]) -> str:
        formatted = [header]
        for line in lines:
            marker = {"added": "+", "removed": "-", "context": " "}[line.kind]
            line_number = line.display_line
            line_label = str(line_number) if line_number is not None else "-"
            formatted.append(f"{marker}{line_label.rjust(5)} | {line.content}")
        return "\n".join(formatted)

    def _coerce_changed_file(self, changed_file: ChangedFile | dict[str, Any]) -> ChangedFile:
        if isinstance(changed_file, ChangedFile):
            return changed_file
        return ChangedFile(
            filename=str(changed_file.get("filename", "")),
            patch=changed_file.get("patch"),
            additions=int(changed_file.get("additions", 0) or 0),
            deletions=int(changed_file.get("deletions", 0) or 0),
            status=str(changed_file.get("status", "modified") or "modified"),
        )

    def _is_diff_metadata(self, line: str) -> bool:
        return line.startswith(("diff --git", "index ", "--- ", "+++ "))
