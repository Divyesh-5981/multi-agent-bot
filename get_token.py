"""Get a GitHub installation token for gh CLI auth."""
from github import Auth, GithubIntegration
from pathlib import Path
from config import Settings

s = Settings.from_env()
private_key = Path(s.github_app_private_key_path).read_text(encoding="utf-8")
app_auth = Auth.AppAuth(s.github_app_id, private_key)
integration = GithubIntegration(auth=app_auth)
access_token = integration.get_access_token(129396834)
print(access_token.token)
