from __future__ import annotations

import asyncio
from dataclasses import replace

from config import Settings
from orchestrator import CodeReviewOrchestrator

SAMPLE_FILES = [
    {
        "filename": "app/auth.py",
        "patch": """@@ -1,6 +1,10 @@
 import sqlite3
 
 def login(email, password):
+    api_key = "sk_test_hardcoded_secret"
+    query = f"SELECT * FROM users WHERE email = '{email}' AND password = '{password}'"
+    conn = sqlite3.connect("app.db")
+    return conn.execute(query).fetchone()
-    return None
""",
        "additions": 4,
        "deletions": 1,
    },
    {
        "filename": "app/users.py",
        "patch": """@@ -10,4 +10,10 @@
 def hydrate_users(users, db):
+    hydrated = []
+    for user in users:
+        for role in db.get_roles():
+            if role.user_id == user.id:
+                hydrated.append((user, role))
+    return hydrated
-    return users
""",
        "additions": 6,
        "deletions": 1,
    },
]


async def main() -> None:
    settings = Settings.from_env()
    if not settings.mock_ai:
        settings = replace(settings, mock_ai=True)
    orchestrator = CodeReviewOrchestrator(settings=settings)
    review = await orchestrator.review_changed_files(SAMPLE_FILES)
    print(review.to_dict())


if __name__ == "__main__":
    asyncio.run(main())
