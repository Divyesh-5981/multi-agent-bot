# Two-Minute Demo Script

## 0:00-0:15 Introduction

I built a multi-agent code review bot powered by four Llama 3.3 70B agents running on Groq's free tier. Each agent specializes in one review discipline, then a synthesizer merges the findings into a GitHub-ready review.

## 0:15-0:45 Show the Pull Request

Open a PR with intentional issues:

- SQL query built with string interpolation
- Hardcoded token or API key
- Nested loop over database-backed data
- Missing error handling around IO or database calls

Explain that this is the type of review work teams usually wait on humans or expensive AI tools to do.

## 0:45-1:15 Explain the Architecture

Show the flow:

```text
PR diff → smart chunking → Security/Performance/Quality agents → Synthesizer → GitHub comment
```

Point out that the chunker keeps each hunk small enough for a 1B model, and the agents run in parallel.

## 1:15-1:45 Highlight the Findings

Show the PR comment:

- Critical SQL injection issue
- Hardcoded secret warning
- Performance warning on nested loop or repeated expensive call
- Review stats with model, tokens, cost, and elapsed time

Emphasize that the bot posts a consolidated comment rather than three noisy independent reviews.

## 1:45-2:00 Closing

The punchline: weak models become strong products when the system design does the heavy lifting. Four focused 1B agents can deliver practical code review feedback at a fraction of the cost of large-model or human-only review.
