"""Simulate a GitHub webhook delivery to test the full webhook flow."""
import hashlib
import hmac
import json
import requests
from config import Settings

s = Settings.from_env()

# Simulate a pull_request opened event
payload = {
    "action": "synchronize",
    "number": 6,
    "pull_request": {
        "number": 6,
        "title": "Feat/GitHub app",
        "state": "open",
        "draft": False,
        "head": {
            "sha": "4021f0a18eeda551687c556bf6164a9359b09d77",
            "ref": "feat/github-app",
        },
        "base": {
            "ref": "main",
        },
    },
    "repository": {
        "full_name": "SujalXplores/multi-agent-bot",
    },
    "installation": {
        "id": 129396834,
    },
}

body = json.dumps(payload).encode("utf-8")

# Sign the payload
signature = "sha256=" + hmac.new(
    s.github_webhook_secret.encode("utf-8"),
    body,
    hashlib.sha256,
).hexdigest()

print(f"Sending webhook to http://localhost:8000/webhook")
print(f"Payload action: {payload['action']}")
print(f"Signature: {signature[:30]}...")

resp = requests.post(
    "http://localhost:8000/webhook",
    data=body,
    headers={
        "Content-Type": "application/json",
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": signature,
    },
    timeout=30,
)

print(f"Response status: {resp.status_code}")
print(f"Response body: {resp.json()}")
