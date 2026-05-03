from __future__ import annotations

import asyncio

from config import Settings
from orchestrator import CodeReviewOrchestrator


def test_orchestrator_reviews_changed_files_in_mock_mode() -> None:
    orchestrator = CodeReviewOrchestrator(settings=Settings(mock_ai=True))
    review = asyncio.run(orchestrator.review_changed_files(
        [
            {
                "filename": "app/auth.py",
                "patch": """@@ -1,3 +1,5 @@
 def login(email):
+    query = f"SELECT * FROM users WHERE email = '{email}'"
+    return db.execute(query)
-    return None
""",
                "additions": 2,
                "deletions": 1,
            }
        ]
    ))

    assert review.critical_count == 1
    assert review.stats.files_reviewed == 1
    assert review.stats.chunks_reviewed == 1
    assert review.stats.lines_added == 2
