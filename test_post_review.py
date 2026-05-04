"""Test posting a review to the PR via the API."""
import requests
import json

resp = requests.post(
    "http://localhost:8000/review/pr",
    json={
        "repo_name": "SujalXplores/multi-agent-bot",
        "pr_number": 6,
        "post_comment": True,
        "installation_id": 129396834,
    },
    timeout=300,
)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"comment_posted: {data.get('comment_posted')}")
print(f"comment_error: {data.get('comment_error')}")
print(f"summary: {data.get('summary', '')[:200]}")
print(f"findings: {len(data.get('findings', []))}")
