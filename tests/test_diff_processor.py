from __future__ import annotations

from app.config import Settings
from app.diff_processor import DiffProcessor
from app.models import ChangedFile


def test_diff_processor_parses_hunk_line_numbers() -> None:
    processor = DiffProcessor(Settings(max_tokens_per_chunk=2000, mock_ai=True))
    chunks = processor.process_changed_files(
        [
            ChangedFile(
                filename="src/app.py",
                patch="""@@ -1,3 +1,4 @@
 def hello():
-    return "hi"
+    name = input("Name: ")
+    return f"hi {name}"
 print("done")
""",
                additions=2,
                deletions=1,
            )
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].file_path == "src/app.py"
    assert chunks[0].language == "Python"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 4
    assert chunks[0].additions == 2
    assert chunks[0].deletions == 1
    assert chunks[0].changed_line_numbers() == [2, 3]


def test_diff_processor_skips_binary_lock_and_vendor_files() -> None:
    processor = DiffProcessor(Settings(mock_ai=True))

    assert not processor.should_review("package-lock.json")
    assert not processor.should_review("assets/logo.png")
    assert not processor.should_review("vendor/library.py")
    assert processor.should_review("src/service.ts")


def test_diff_processor_splits_large_hunks() -> None:
    processor = DiffProcessor(Settings(max_tokens_per_chunk=20, mock_ai=True))
    patch_lines = ["@@ -1,1 +1,8 @@", " def work():"]
    patch_lines.extend(f"+    value_{index} = '{'x' * 30}'" for index in range(8))
    chunks = processor.process_changed_files(
        [ChangedFile(filename="src/big.py", patch="\n".join(patch_lines), additions=8, deletions=0)]
    )

    assert len(chunks) > 1
    assert sum(chunk.additions for chunk in chunks) == 8
