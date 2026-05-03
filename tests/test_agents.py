from __future__ import annotations

import asyncio

from agents import AgentSystem
from config import Settings
from diff_processor import DiffProcessor
from models import ChangedFile, Finding


def _sample_chunk():
    processor = DiffProcessor(Settings(mock_ai=True))
    return processor.process_changed_files(
        [
            ChangedFile(
                filename="app/auth.py",
                patch="""@@ -1,3 +1,4 @@
 def login(email):
+    query = f"SELECT * FROM users WHERE email = '{email}'"
+    return db.execute(query)
-    return None
""",
                additions=2,
                deletions=1,
            )
        ]
    )[0]


def test_parse_findings_extracts_json_from_markdown() -> None:
    agent_system = AgentSystem(Settings(mock_ai=True))
    response = """Here is the result:
```json
{"findings":[{"line":2,"severity":"high","issue":"x","suggestion":"y"}]}
```
"""

    findings = agent_system.parse_findings(response)

    assert findings == [{"line": 2, "severity": "high", "issue": "x", "suggestion": "y"}]


def test_mock_security_agent_detects_sql_injection() -> None:
    agent_system = AgentSystem(Settings(mock_ai=True))
    findings = asyncio.run(agent_system.review_chunk(_sample_chunk(), "security"))

    assert findings
    assert findings[0].category == "security"
    assert findings[0].severity == "critical"
    assert findings[0].line == 2


def test_synthesis_deduplicates_and_counts() -> None:
    agent_system = AgentSystem(Settings(mock_ai=True))
    review = asyncio.run(agent_system.synthesize(
        {
            "security": [
                Finding("app.py", 10, "medium", "security", "Same issue", "Fix it", 0.7),
                Finding("app.py", 10, "high", "security", "Same issue", "Fix better", 0.8),
            ],
            "performance": [],
            "quality": [Finding("app.py", 20, "low", "quality", "Quality issue", "Clean it", 0.6)],
        }
    ))

    assert review.high_count == 1
    assert review.low_count == 1
    assert len(review.findings) == 2
