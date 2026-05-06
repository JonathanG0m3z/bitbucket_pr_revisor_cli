# Bitbucket PR Reviewer CLI

> Automated Pull Request review system powered by **LangGraph** and a single AI CLI agent that covers security, performance, and code style in one pass.

---

## Overview

This tool fetches the diff of any private Bitbucket Pull Request and passes it to a single AI CLI process that produces a consolidated review with a 0–10 quality score and a prioritized action list.

When `CLI=gemini`, the Gemini CLI internally delegates to three specialist subagents running in parallel — parallelism happens inside Gemini's own orchestration layer, not in LangGraph.

```
PR URL
  │
  ▼
connect_bitbucket  (validates credentials via GET /2.0/user)
  │
  ▼
fetch_diff  (GET /2.0/repositories/{ws}/{repo}/pullrequests/{id}/diff)
  │
  ▼
run_cli  ──── claude / codex: unified prompt (security + performance + style in one pass)
         └─── gemini: orchestrator prompt → @security_reviewer
                                          → @performance_reviewer   (parallel internally)
                                          → @style_reviewer
  │
  ▼
report  (unified JSON: score, severity, issues per section, top_actions, summary)
```

---

## Features

- **Single CLI process** — one subprocess call covers all three review dimensions; no coordination overhead.
- **Gemini subagent mode** — when `CLI=gemini`, three specialist subagents (`@security_reviewer`, `@performance_reviewer`, `@style_reviewer`) run in parallel inside Gemini's own orchestration layer.
- **Pluggable AI backends** — set `CLI=claude`, `CLI=codex`, or `CLI=gemini` to switch backends.
- **Private Bitbucket support** — authenticates via Bitbucket API Token (Basic auth) or App Password; no OAuth dance required.
- **Credential validation upfront** — `connect_bitbucket` node validates credentials before fetching the diff, giving immediate feedback on auth issues.
- **Full-diff context** — the entire diff is sent in a single CLI call. Modern context windows (Gemini 2.5 Pro: 1M tokens, Claude Sonnet: 200K, Codex: 128K) handle typical PRs without splitting.
- **Structured output** — the CLI responds in JSON; `main.py` parses and prints each section with issues and line numbers.
- **120-second timeout** per CLI call with clean temp-file teardown.

---

## Requirements

| Dependency | Version |
|---|---|
| Python | 3.11+ |
| LangGraph | ≥ 0.2 |
| httpx | ≥ 0.27 |
| python-dotenv | ≥ 1.0 |

At least one of the following CLIs must be installed and authenticated:

| CLI | Install | Price |
|---|---|---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `npm install -g @anthropic-ai/claude-code` | $20/mo Pro |
| [OpenAI Codex](https://github.com/openai/codex) | `npm install -g @openai/codex` | Included in ChatGPT Plus $20/mo |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` | Free (1 000 req/day) |

---

## Installation

```bash
git clone https://github.com/your-org/bitbucket_pr_revisor_cli.git
cd bitbucket_pr_revisor_cli

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
```

---

## Configuration

All configuration is done through environment variables. Copy `.env.example` to `.env` and fill in the values.

### Bitbucket Authentication

Use **one** of the two strategies:

| Strategy | Variables | Auth type |
|---|---|---|
| API Token *(recommended)* | `BITBUCKET_EMAIL` + `BITBUCKET_TOKEN` | Basic auth |
| App Password | `BITBUCKET_USER` + `BITBUCKET_APP_PASSWORD` | Basic auth |

**API Token setup** (recommended):
1. Go to **bitbucket.org → your avatar → Account settings → Security → API tokens**
2. Click **Create API token with scopes**
3. Enable both: **Repositories: Read** + **Pull requests: Read**
4. Set `BITBUCKET_EMAIL` to your Atlassian account email and `BITBUCKET_TOKEN` to the generated token

If both strategies are configured, API Token takes precedence.

### AI CLI Selection

```env
CLI=claude   # claude | codex | gemini
```

A single variable controls which CLI backend runs the full review.

| Value | Behavior |
|---|---|
| `claude` | Single unified prompt covering all three dimensions |
| `codex` | Single unified prompt covering all three dimensions |
| `gemini` | Orchestrator prompt delegates to `@security_reviewer`, `@performance_reviewer`, `@style_reviewer` in parallel |

### API Keys (if required by your CLI)

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
```

---

## Usage

```bash
python main.py "https://bitbucket.org/myworkspace/myrepo/pull-requests/42"
```

### Example Output

```
════════════════════════════════════════
 PR REVIEW  —  Score: 6/10  |  Severity: HIGH
════════════════════════════════════════

════════════════════════════════════════
 SECURITY REVIEW
════════════════════════════════════════
One critical vulnerability found in the authentication module.
  Line 17: [vuln] Hardcoded AWS key in config.py

════════════════════════════════════════
 PERFORMANCE REVIEW
════════════════════════════════════════
No significant performance issues detected.

════════════════════════════════════════
 STYLE REVIEW
════════════════════════════════════════
Minor naming inconsistencies found.
  Line 34: [style] Function name does not follow snake_case convention

════════════════════════════════════════
 TOP 5 ACTIONS
════════════════════════════════════════
1. [CRITICAL] Remove hardcoded AWS key on line 17 (config.py)
2. Rename function on line 34 to follow snake_case
...

════════════════════════════════════════
 EXECUTIVE SUMMARY
════════════════════════════════════════
The PR introduces one critical security vulnerability...
```

---

## Project Structure

```
bitbucket_pr_revisor_cli/
├── main.py              # Entry point — accepts PR URL, runs graph, prints report
├── graph.py             # LangGraph StateGraph: 3 linear nodes
├── agents.py            # Unified agent runner, prompts, diff splitter, chunk merger
├── bitbucket.py         # httpx client: connect() + fetch_diff(), URL parser, auth
├── requirements.txt
├── .env.example
├── .gemini/
│   └── agents/
│       ├── security_reviewer.md    # Gemini subagent: security specialist
│       ├── performance_reviewer.md # Gemini subagent: performance specialist
│       └── style_reviewer.md       # Gemini subagent: style specialist
└── tests/
    ├── test_bitbucket.py
    ├── test_agents.py
    └── test_graph.py
```

---

## Architecture Details

### Graph State

```python
class AgentState(TypedDict):
    pr_url: str
    auth: dict    # {"strategy": "token"|"app_password", "credentials": (user, secret)}
    diff: str
    report: str
```

The `auth` field is populated by `connect_bitbucket` and consumed by `fetch_diff`, keeping credential resolution isolated from diff fetching.

### Linear Pipeline

Three nodes, no fan-out:

```python
workflow.add_edge(START, "connect_bitbucket")
workflow.add_edge("connect_bitbucket", "fetch_diff")
workflow.add_edge("fetch_diff", "run_cli")
workflow.add_edge("run_cli", END)
```

### Gemini Subagent Mode

When `CLI=gemini`, the orchestrator prompt references the three subagents using Gemini CLI's native `@agent_name` syntax. Gemini resolves these against `.gemini/agents/*.md` files at runtime and runs them in parallel internally. Results are consolidated into a single JSON response by the Gemini orchestrator before returning to the Python process.

Subagent files require Gemini CLI v0.38.1+.

## Running Tests

```bash
pytest -v
```

Tests mock both `httpx` (Bitbucket client) and `asyncio.create_subprocess_exec` (CLI runner) — no real credentials or installed CLIs are needed to run the test suite.

---

## Security Notes

- Credentials are **never** hardcoded. They are always read from environment variables.
- Temporary prompt files are written to the system temp directory and deleted immediately after CLI execution.
- The `.env` file is excluded from version control via `.gitignore`.

---

## License

MIT
