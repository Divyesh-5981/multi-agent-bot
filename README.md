# Multi-Agent Code Review Bot 🤖

> Four small Gemma agents working together like a focused senior code review team.

This project implements the full MVP described in `plan.txt`: a GitHub pull request review bot where specialized 1B-parameter agents independently inspect a PR diff for security, performance, and code quality issues, then a synthesizer consolidates the final review into one GitHub comment.

## Why It Is Different

- **Small-model leverage:** Uses `google/gemma-3-1b-it` by default, configurable with `HF_MODEL_ID`.
- **Multi-agent specialization:** Security, Performance, and Quality reviewers each receive a focused prompt.
- **Parallel execution:** Agents run concurrently across diff chunks.
- **Smart chunking:** Unified diffs are parsed by file/hunk and capped for small-model context windows.
- **Production-shaped MVP:** Webhook signature verification, retry handling, JSON repair, line-number validation, and dry-run/mock testing are included.

## Architecture

```text
GitHub PR Webhook
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
GitHub PR comment
```

## Project Structure

```text
.
├── agents.py                  # Gemma prompts, HF calls, JSON parsing, mock reviewers, synthesis
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

Edit `.env`:

```env
GITHUB_TOKEN=ghp_replace_with_a_token_that_can_read_pull_requests_and_write_comments
GITHUB_WEBHOOK_SECRET=replace_with_a_random_webhook_secret
HF_API_TOKEN=hf_replace_with_your_huggingface_token
HF_MODEL_ID=google/gemma-3-1b-it
POST_GITHUB_COMMENT=true
MOCK_AI=false
```

## GitHub Token Permissions

For a fine-grained GitHub token, grant access only to the target repository:

- **Contents:** Read
- **Pull requests:** Read
- **Issues:** Read and write
- **Metadata:** Read

GitHub PR comments are issue comments, so write access to Issues is required.

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
  "post_comment": true
}
```

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

In GitHub:

- **Repository Settings → Webhooks → Add webhook**
- **Payload URL:** `https://your-ngrok-host/webhook`
- **Content type:** `application/json`
- **Secret:** same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** Pull requests

## Model Declaration

| Component | Model | Purpose |
|---|---|---|
| Security Agent | `google/gemma-3-1b-it` | Finds security vulnerabilities |
| Performance Agent | `google/gemma-3-1b-it` | Finds performance anti-patterns |
| Quality Agent | `google/gemma-3-1b-it` | Finds maintainability and validation issues |
| Synthesizer | `google/gemma-3-1b-it` | Deduplicates, prioritizes, and summarizes |

If your Hugging Face account or inference provider does not expose that model, set `HF_MODEL_ID` to another compatible instruction-tuned Gemma 1B model.

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
- Inline GitHub review comments are not implemented yet; this MVP posts a single consolidated PR comment.
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
