"""Update the GitHub App webhook URL to point to the cloudflared tunnel."""
import time
import jwt
import requests
from pathlib import Path
from config import Settings

TUNNEL_URL = "https://agencies-combining-amendment-metropolitan.trycloudflare.com"

s = Settings.from_env()
private_key = Path(s.github_app_private_key_path).read_text(encoding="utf-8")

# Create JWT for GitHub App
now = int(time.time())
payload = {
    "iat": now - 60,
    "exp": now + (10 * 60),
    "iss": str(s.github_app_id),
}
encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

# Get current app config
headers = {
    "Authorization": f"Bearer {encoded_jwt}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Check current webhook config
resp = requests.get("https://api.github.com/app", headers=headers)
print(f"GET /app status: {resp.status_code}")
if resp.status_code == 200:
    app_data = resp.json()
    print(f"App name: {app_data.get('name')}")
    print(f"Current webhook URL: {app_data.get('events', 'N/A')}")
    
# Get hook config
resp = requests.get("https://api.github.com/app/hook/config", headers=headers)
print(f"\nGET /app/hook/config status: {resp.status_code}")
if resp.status_code == 200:
    hook_config = resp.json()
    print(f"Current URL: {hook_config.get('url')}")
    print(f"Content type: {hook_config.get('content_type')}")
    print(f"Secret set: {bool(hook_config.get('secret'))}")

# Update webhook URL
new_webhook_url = f"{TUNNEL_URL}/webhook"
print(f"\nUpdating webhook URL to: {new_webhook_url}")

resp = requests.patch(
    "https://api.github.com/app/hook/config",
    headers=headers,
    json={
        "url": new_webhook_url,
        "content_type": "json",
        "secret": s.github_webhook_secret,
    },
)
print(f"PATCH status: {resp.status_code}")
if resp.status_code == 200:
    updated = resp.json()
    print(f"Updated URL: {updated.get('url')}")
    print("✅ Webhook URL updated successfully!")
else:
    print(f"Error: {resp.text}")
