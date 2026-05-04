# Multi-Agent Code Review Bot 🤖

> Four small Gemma agents working together like a focused senior code review team.

This project implements the full MVP described in `plan.txt`: a GitHub pull request review bot where specialized 1B-parameter agents independently inspect a PR diff for security, performance, and code quality issues, then a synthesizer consolidates the final review into one GitHub comment.

## Why It Is Different

- **Configurable model provider:** Uses an OpenAI-compatible chat completions endpoint by default, configurable with `HF_MODEL_ID` and `HF_API_BASE_URL`.
- **Multi-agent specialization:** Security, Performance, and Quality reviewers each receive a focused prompt.
- **Parallel execution:** Agents run concurrently across diff chunks.
- **Smart chunking:** Unified diffs are parsed by file/hunk and capped for small-model context windows.
- **Production-shaped MVP:** Webhook signature verification, retry handling, JSON repair, line-number validation, and dry-run/mock testing are included.

## Architecture

```text
GitHub App PR Webhook
        |
        v
FastAPI /webhook
        |
        v
GitHubClient fetches changed files
        |
        v
DiffProcessor filters + chunks unified diffs
        |
        v
Security Agent + Performance Agent + Quality Agent
        |
        v
Synthesizer dedupes, prioritizes, and summarizes
        |
        v
GitHub PR review from the app bot
```

## Project Structure

```text
.
├── agents.py                  # Agent prompts, model API calls, JSON parsing, mock reviewers, synthesis
├── config.py                  # Environment-driven settings
├── diff_processor.py          # Diff filtering, language detection, hunk parsing, chunking
├── github_client.py           # PyGithub wrapper, webhook HMAC, PR comment formatter
├── main.py                    # FastAPI server and API endpoints
├── models.py                  # Shared dataclasses and severity helpers
├── orchestrator.py            # End-to-end review workflow
├── test_review.py             # Local mock demo script
├── tests/                     # Unit/integration tests
├── requirements.txt
├── .env.example
└── plan.txt
```

## Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Edit `.env` on the hosted bot server:

```env
GITHUB_WEBHOOK_SECRET=replace_with_a_random_webhook_secret
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=./github-app-private-key.pem
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_INSTALLATION_ID=
GITHUB_TOKEN=
HF_API_TOKEN=replace_with_your_model_provider_token
HF_MODEL_ID=llama-3.3-70b-versatile
HF_API_BASE_URL=https://api.groq.com/openai/v1
POST_GITHUB_COMMENT=true
MOCK_AI=false
```

For installable usage, only the hosted bot operator configures these environment variables. Repository owners install the GitHub App and do not need to create `.env` files or personal access tokens.

## GitHub App Setup

### 1. Create the GitHub App

Navigate to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.

Fill out the registration form with these exact fields:

| Field | Example value | Notes |
|---|---|---|
| **GitHub App name** | `Multi-Agent Review Bot` | This becomes the visible bot name on PR comments. Must be unique across GitHub. |
| **Description** | `Automated multi-agent code review for pull requests` | Shown on the public app page. |
| **Homepage URL** | `https://your-bot-docs.example.com` | Can be your repo README or docs site. |
| **Webhook URL** | `https://your-hosted-bot.example.com/webhook` | Must match the `/webhook` path on your deployed bot. |
| **Webhook secret** | `a_random_32_char_string` | Same value you set as `GITHUB_WEBHOOK_SECRET` in the bot `.env`. |

Under **Permissions → Repository permissions**, set:

- **Contents:** Read-only
- **Pull requests:** Read and write
- **Metadata:** Read-only

Under **Subscribe to events**, check:

- **Pull request**

Click **Create GitHub App**.

### 2. Note the App ID

After creation, the app settings page shows an **App ID** (numeric). Copy it into your bot `.env`:

```env
GITHUB_APP_ID=1234567
```

### 3. Generate a private key

On the app settings page:

1. Scroll to **Private keys**
2. Click **Generate a private key**
3. GitHub downloads a `.pem` file, for example `multi-agent-review-bot.2026-01-01.private-key.pem`
4. Move it to your deployed server securely
5. Set the path in your bot `.env`:

```env
GITHUB_APP_PRIVATE_KEY_PATH=/secure/path/to/multi-agent-review-bot.2026-01-01.private-key.pem
```

Alternatively, you can paste the entire PEM contents (with `\n` line breaks) directly into `GITHUB_APP_PRIVATE_KEY` if your hosting environment does not support file mounts.

### 4. Install the app on a repository

From the app settings page:

1. Click **Install App** (left sidebar)
2. Choose your user or organization
3. Select **Only select repositories** and pick the repositories you want reviewed
4. Click **Install**

After installation, the browser URL will look like:

```text
https://github.com/settings/installations/98765432
```

The number at the end (`98765432`) is the **Installation ID**. You do not need to write it into `.env` for normal webhook usage because GitHub sends it in every webhook payload. It is only needed if you run manual `/review/pr` API calls against that specific installation.

### 5. Configure the bot profile

The bot name and avatar shown on PR comments are controlled by the GitHub App profile, not by code:

- **App name:** `Multi-Agent Review Bot` → comments show as `Multi-Agent Review Bot[bot]`
- **App logo/avatar:** Upload a square PNG under **Display information** on the app settings page
- **Description/Homepage:** Public app profile details

If you want a different displayed name, you must change it in the GitHub App settings and reinstall.

Installers (repository owners) only need to install the GitHub App. They do not need to create `.env` files or personal access tokens.

### Optional Personal Token Fallback

Comments posted with `GITHUB_TOKEN` are attributed to the user or token owner. Use GitHub App authentication for bot-branded comments.

`GITHUB_TOKEN` is still supported for local development or one-off manual runs. For a fine-grained token, grant access only to the target repository:

- **Contents:** Read
- **Pull requests:** Read and write
- **Metadata:** Read

## Running Locally

### Mock AI demo without external API keys

```bash
set MOCK_AI=true
python test_review.py
```

PowerShell:

```powershell
$env:MOCK_AI="true"
python test_review.py
```

### Start the API server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000/docs
```

## API Endpoints

### `GET /`

Returns runtime status, selected model, agent list, and whether GitHub/Hugging Face credentials are configured.

### `POST /review/local`

Reviews a provided list of changed files without GitHub. Useful for tests and demos.

Example body:

```json
{
  "post_comment": false,
  "files": [
    {
      "filename": "app/auth.py",
      "patch": "@@ -1,3 +1,5 @@\n def login(email):\n+    query = f\"SELECT * FROM users WHERE email = '{email}'\"\n+    return db.execute(query)\n-    return None\n",
      "additions": 2,
      "deletions": 1
    }
  ]
}
```

### `POST /review/pr`

Fetches and reviews a live GitHub PR.

```json
{
  "repo_name": "owner/repo",
  "pr_number": 1,
  "post_comment": true,
  "installation_id": 12345678
}
```

`installation_id` is optional for manual calls. Webhook-triggered reviews receive it automatically from GitHub.

### `POST /webhook`

Receives GitHub pull request webhooks. Supported actions:

- `opened`
- `reopened`
- `synchronize`
- `ready_for_review`

Draft PRs and unrelated events are ignored.

## Webhook Setup

For local testing, expose port `8000` with a tunnel such as ngrok:

```bash
ngrok http 8000
```

In the GitHub App settings:

- **Webhook URL:** `https://your-ngrok-host/webhook`
- **Content type:** `application/json`
- **Secret:** same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** Pull request

## Model Declaration

| Component | Model | Purpose |
|---|---|---|
| Security Agent | `HF_MODEL_ID` | Finds security vulnerabilities |
| Performance Agent | `HF_MODEL_ID` | Finds performance anti-patterns |
| Quality Agent | `HF_MODEL_ID` | Finds maintainability and validation issues |
| Synthesizer | `SYNTHESIZER_MODEL_ID` or `HF_MODEL_ID` | Deduplicates, prioritizes, and summarizes |

The default configuration uses Groq's OpenAI-compatible API shape. Set `HF_API_BASE_URL` to another OpenAI-compatible `/chat/completions` base URL if you use a different inference provider.

## Cost Breakdown

The app tracks a rough token estimate using the common `1 token ≈ 4 chars` approximation.

| PR Size | Estimated Tokens | Estimated Cost at `$0.0001 / 1K` |
|---|---:|---:|
| Small, 5 files | 3,000 | $0.0003 |
| Medium, 20 files | 10,000 | $0.0010 |
| Large, 50 files | 25,000 | $0.0025 |

The exact cost depends on your inference provider and account plan.

## Review Comment Format

The generated PR comment includes:

- **Summary:** Friendly overview and issue counts
- **Severity groups:** Critical, High, Medium, Low
- **Line references:** `file:line`
- **Category:** Security, Performance, or Quality
- **Suggestion:** Actionable fix guidance
- **Stats:** Files, chunks, lines changed, model, tokens, cost, and elapsed time

## Testing

```bash
pytest
```

The test suite uses `MOCK_AI=true` style settings and does not call external services.

## Known Limitations

- The model can miss context-dependent design or business-logic bugs.
- Very large PRs are capped by `MAX_REVIEW_CHUNKS` to keep latency bounded.
- The Hugging Face hosted inference API may require model access approval depending on the selected model.
- Inline GitHub review comments are posted when findings map to valid changed diff lines.
- The JSON parser is defensive, but malformed model output can still be dropped gracefully.

## Demo Script

1. Start with a PR that introduces a string-built SQL query, a hardcoded token, and a nested loop.
2. Open or update the PR.
3. GitHub sends the webhook to `/webhook`.
4. The bot chunks the diff and runs three focused agents in parallel.
5. The synthesizer merges results and posts the GitHub comment.
6. Highlight that this is four 1B agents doing a useful review at a tiny estimated cost.

## Roadmap

- Inline GitHub suggested changes
- Custom `.code-review-bot.yml` rules
- Per-repository dashboards and trend metrics
- Optional local inference backend
- Better source-code context around each diff hunk

## License

MIT
