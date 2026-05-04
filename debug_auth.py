"""Debug GitHub App authentication and installation."""
from github import Auth, GithubIntegration
from pathlib import Path
from config import Settings

s = Settings.from_env()
private_key = Path(s.github_app_private_key_path).read_text(encoding="utf-8")
app_auth = Auth.AppAuth(s.github_app_id, private_key)
integration = GithubIntegration(auth=app_auth)

installations = list(integration.get_installations())
for inst in installations:
    print(f"Installation ID: {inst.id}")
    print(f"Account: {inst.account}")
    print(f"Target type: {inst.target_type}")
    perms = inst.raw_data.get("permissions", {})
    print(f"Permissions: {perms}")
    events = inst.raw_data.get("events", [])
    print(f"Events: {events}")
    try:
        repos = integration.get_repos(inst.id)
        print("Repos:")
        for r in repos.get_page(0):
            print(f"  - {r.full_name}")
    except Exception as e:
        print(f"Error listing repos: {e}")
    print()

# Now try to get an access token and fetch the PR
print("--- Testing PR access ---")
try:
    access_token = integration.get_access_token(inst.id)
    print(f"Got access token: {access_token.token[:10]}...")
    from github import Github
    gh = Github(auth=Auth.Token(access_token.token))
    repo = gh.get_repo("Divyesh-5981/multi-agent-bot")
    pr = repo.get_pull(6)
    print(f"PR #{pr.number}: {pr.title}")
    print(f"PR state: {pr.state}")
    print(f"PR draft: {pr.draft}")
    files = list(pr.get_files())
    print(f"Changed files: {len(files)}")
    for f in files:
        print(f"  - {f.filename} (+{f.additions}/-{f.deletions})")
except Exception as e:
    print(f"Error: {e}")
