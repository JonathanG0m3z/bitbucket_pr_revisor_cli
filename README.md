# Bitbucket PR Reviewer CLI

> Automated Pull Request review system powered by **LangGraph** and three specialized AI CLI agents running in true parallel.

---

## Overview

This tool fetches the diff of any private Bitbucket Pull Request and distributes it to three independent AI agents — each focused on a different review dimension. The results are consolidated into a single executive report with a 0–10 quality score and a prioritized action list.

```
PR URL
  │
  ▼
fetch_pr  ──►  router  ──┬──►  security_agent   ──┐
                         ├──►  performance_agent ──┤──►  consolidate  ──►  final report
                         └──►  style_agent       ──┘
```

---

## Features

- **Parallel execution** — the three agents run concurrently via LangGraph's Send API; no sequential bottleneck.
- **Pluggable AI backends** — each agent can be independently assigned to Claude Code, OpenAI Codex, or Gemini CLI through environment variables.
- **Private Bitbucket support** — authenticates via Bitbucket API Token (Basic auth) or App Password; no OAuth dance required.
- **Large diff handling** — diffs exceeding 8 000 characters are automatically split at file boundaries (max 3 files per CLI call).
- **Structured output** — every agent responds in JSON; the consolidator produces an executive summary with a Top 5 action list.
- **120-second timeout** per agent with clean temp-file teardown.

---

## Requirements

| Dependency | Version |
|---|---|
| Python | 3.11+ |
| LangGraph | ≥ 0.2 |
| httpx | ≥ 0.27 |
| python-dotenv | ≥ 1.0 |

At least one of the following CLIs must be installed and authenticated:

| CLI | Install |
|---|---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `npm install -g @anthropic-ai/claude-code` |
| [OpenAI Codex](https://github.com/openai/codex) | `npm install -g @openai/codex` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `npm install -g @google/gemini-cli` |

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

### AI CLI Keys

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
```

### Agent CLI Assignment

```env
CLI_SECURITY=claude       # claude | codex | gemini
CLI_PERFORMANCE=codex
CLI_STYLE=gemini
```

Each variable controls which CLI backend runs that specific agent. Mix and match freely.

---

## Usage

```bash
python main.py "https://bitbucket.org/myworkspace/myrepo/pull-requests/42"
```

### Example Output

```
════════════════════════════════════════
 SECURITY REPORT
════════════════════════════════════════
{
  "issues": [
    {"line": 17, "type": "vuln", "description": "Hardcoded AWS key in config.py"}
  ],
  "severity": "critical",
  "summary": "One critical vulnerability found."
}

════════════════════════════════════════
 PERFORMANCE REPORT
════════════════════════════════════════
{
  "issues": [],
  "severity": "low",
  "summary": "No significant performance issues detected."
}

════════════════════════════════════════
 STYLE REPORT
════════════════════════════════════════
{
  "issues": [
    {"line": 34, "type": "style", "description": "Function name does not follow snake_case convention"}
  ],
  "severity": "medium",
  "summary": "Minor naming inconsistencies."
}

════════════════════════════════════════
 EXECUTIVE SUMMARY  —  Score: 4/10
════════════════════════════════════════
Top 5 Actions:
1. [CRITICAL] Remove hardcoded AWS key on line 17 (config.py)
...
```

---

## Project Structure

```
bitbucket_pr_revisor_cli/
├── main.py          # Entry point — accepts PR URL, runs graph, prints report
├── graph.py         # LangGraph StateGraph: nodes, edges, fan-out via Send API
├── agents.py        # Async agent functions, CLI subprocess runner, prompt constants
├── bitbucket.py     # httpx client: URL parser, auth, diff fetcher
├── requirements.txt
├── .env.example
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
    diff: str
    security_report: str
    performance_report: str
    style_report: str
    final_report: str
    reviews: Annotated[list, operator.add]  # concurrent-safe accumulator
```

The `reviews` field uses `operator.add` as a reducer, allowing all three agent nodes to write to it simultaneously without race conditions.

### Fan-out via Send API

The `router` node does not call agents sequentially. It returns a list of `Send` objects — LangGraph schedules all three as independent parallel branches:

```python
def router(state: AgentState) -> list[Send]:
    return [
        Send("security_agent", state),
        Send("performance_agent", state),
        Send("style_agent", state),
    ]
```

### CLI Integration Pattern

Each agent:
1. Writes a specialized prompt + diff chunk to a temporary `.md` file.
2. Invokes the CLI via `asyncio.create_subprocess_exec`.
3. Awaits completion with a 120-second hard timeout.
4. Cleans up the temp file in a `finally` block regardless of outcome.

### Large Diff Handling

If the diff exceeds 8 000 characters, `split_diff()` splits it at `diff --git` markers, grouping at most 3 files per chunk. Each chunk is processed independently and results are concatenated.

---

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
