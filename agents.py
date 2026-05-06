import asyncio
import os
import re
import tempfile
import logging

logger = logging.getLogger(__name__)

UNIFIED_PROMPT = """You are a senior engineering lead performing a code review. Analyze the following git diff across security, performance, and code style. Be CONCISE and DIRECT. No fluff.

Respond ONLY with valid JSON. No markdown, no explanation, no code fences.

Required JSON schema:
{
  "score": <integer 0-10>,
  "overall_severity": "<critical|high|medium|low>",
  "security": {
    "issues": [{"line": <integer or null>, "type": "vuln", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "performance": {
    "issues": [{"line": <integer or null>, "type": "perf", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "style": {
    "issues": [{"line": <integer or null>, "type": "style", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "critical_actions": ["<only CRITICAL-severity actions — must fix before merge>"],
  "executive_summary": "<two or three sentences, under 60 words total>"
}

RULES:
- `critical_actions`: ONLY include actions for CRITICAL severity issues. If there are no critical issues, return an empty array [].
- Descriptions and summaries must be short, factual, no filler words.
- No "the code does X" narration — state the issue and impact only.

Security — find: vulnerabilities, hardcoded secrets, injections, missing auth checks, XSS.
Performance — find: N+1 queries, O(n^2) algorithms, blocking I/O in async, memory leaks.
Style — find: naming violations, missing types, SOLID violations, duplication, dead code.

If no issues in a dimension, return empty issues array with severity "low" and a one-line summary.

DIFF TO ANALYZE:
"""

GEMINI_ORCHESTRATOR_PROMPT = """You are a senior engineering lead orchestrating a PR code review. Be CONCISE and DIRECT.

Delegate the diff below to all three specialist subagents IN PARALLEL:
- @security_reviewer — vulnerabilities, secrets, injections, auth gaps
- @performance_reviewer — N+1, O(n^2), blocking I/O, memory leaks
- @style_reviewer — naming, SOLID, missing types, duplication

Consolidate their findings into a single concise JSON report.

Respond ONLY with valid JSON. No markdown, no explanation, no code fences.

Required JSON schema:
{
  "score": <integer 0-10>,
  "overall_severity": "<critical|high|medium|low>",
  "security": {
    "issues": [{"line": <integer or null>, "type": "vuln", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "performance": {
    "issues": [{"line": <integer or null>, "type": "perf", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "style": {
    "issues": [{"line": <integer or null>, "type": "style", "description": "<under 15 words>"}],
    "severity": "<critical|high|medium|low>",
    "summary": "<one sentence, under 25 words>"
  },
  "critical_actions": ["<only CRITICAL-severity actions — must fix before merge>"],
  "executive_summary": "<two or three sentences, under 60 words total>"
}

RULES:
- `critical_actions`: ONLY include actions for CRITICAL severity issues. Empty array [] if none.
- Short descriptions, no filler words. State the issue and impact, nothing else.

DIFF TO ANALYZE:
"""


def build_command(cli: str, prompt_file: str | None) -> list[str]:
    logger.debug("Building command for CLI: %s", cli)
    if cli == "claude":
        return ["claude", "--print", prompt_file]
    if cli == "codex":
        # Codex CLI v0.x: prompt is read from stdin when '-' is passed.
        return ["codex", "exec", "--full-auto", "-"]
    if cli == "gemini":
        return ["gemini", "--yolo", prompt_file]
    logger.error("Unknown CLI requested: %s", cli)
    raise ValueError(f"Unknown CLI: {cli!r}. Valid options: claude, codex, gemini")


async def run_cli_agent(prompt: str, diff: str, cli: str) -> str:
    debug = bool(os.getenv("DEBUG_CLI"))
    full_prompt = prompt + diff
    use_stdin = cli == "codex"
    tmp_path: str | None = None

    try:
        if use_stdin:
            cmd = build_command(cli, None)
            stdin_data: bytes | None = full_prompt.encode("utf-8")
            logger.info("Running %s agent (prompt via stdin)", cli)
        else:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            )
            tmp_path = tmp.name
            tmp.write(full_prompt)
            tmp.flush()
            tmp.close()
            cmd = build_command(cli, tmp_path)
            stdin_data = None
            logger.info("Running %s agent (tmp file: %s)", cli, tmp_path)

        if debug:
            print(f"[DEBUG_CLI] Running: {' '.join(cmd)}", flush=True)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE if use_stdin else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=None if debug else asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=120
            )
        except asyncio.TimeoutError:
            logger.error("%s agent timed out after 120 seconds", cli)
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return (
                '{"score": 0, "overall_severity": "low",'
                ' "security": {"issues": [], "severity": "low", "summary": "Agent timed out."},'
                ' "performance": {"issues": [], "severity": "low", "summary": ""},'
                ' "style": {"issues": [], "severity": "low", "summary": ""},'
                ' "top_actions": [], "executive_summary": "Agent timed out after 120 seconds."}'
            )

        if proc.returncode != 0:
            err = (stderr.decode("utf-8", errors="replace").strip()[:100]
                   if stderr else "(stderr streamed to terminal)")
            logger.error("%s agent failed with return code %d: %s", cli, proc.returncode, err)
            return (
                f'{{"score": 0, "overall_severity": "low",'
                f' "security": {{"issues": [], "severity": "low", "summary": "CLI error: {err}"}},'
                f' "performance": {{"issues": [], "severity": "low", "summary": ""}},'
                f' "style": {{"issues": [], "severity": "low", "summary": ""}},'
                f' "top_actions": [], "executive_summary": "Agent failed."}}'
            )

        logger.info("%s agent finished successfully", cli)
        return stdout.decode("utf-8", errors="replace").strip()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def split_diff(diff: str, max_files: int = 3, max_chars: int = 8000) -> list[str]:
    """
    Splits a unified diff into chunks. 
    Each chunk contains at most max_files files and is at most max_chars long.
    """
    logger.debug("Splitting diff (max_files=%d, max_chars=%d)", max_files, max_chars)
    if not diff:
        return []

    # Regex to find "diff --git" lines which start a new file's diff
    file_starts = [m.start() for m in re.finditer(r"^diff --git ", diff, re.MULTILINE)]
    
    if not file_starts:
        return [diff] if len(diff) <= max_chars else [diff[:max_chars]]

    chunks = []
    current_chunk_start = 0
    current_file_count = 0
    
    for i in range(len(file_starts)):
        next_file_start = file_starts[i+1] if i+1 < len(file_starts) else len(diff)
        
        # Would adding this file exceed limits?
        potential_chunk_end = next_file_start
        chunk_len = potential_chunk_end - current_chunk_start
        
        if (current_file_count >= max_files) or (chunk_len > max_chars and current_file_count > 0):
            # Close current chunk and start a new one
            chunks.append(diff[current_chunk_start:file_starts[i]])
            current_chunk_start = file_starts[i]
            current_file_count = 1
        else:
            current_file_count += 1
            
    # Add the last chunk
    chunks.append(diff[current_chunk_start:])
    logger.debug("Diff split into %d chunks", len(chunks))
    return chunks


async def security_agent(diff: str, cli: str) -> str:
    # This is a legacy wrapper for tests
    return await run_cli_agent(UNIFIED_PROMPT, diff, cli)

async def performance_agent(diff: str, cli: str) -> str:
    # This is a legacy wrapper for tests
    return await run_cli_agent(UNIFIED_PROMPT, diff, cli)

async def style_agent(diff: str, cli: str) -> str:
    # This is a legacy wrapper for tests
    return await run_cli_agent(UNIFIED_PROMPT, diff, cli)


async def run_review(diff: str, cli: str) -> str:
    logger.debug("Starting review with CLI: %s", cli)
    prompt = GEMINI_ORCHESTRATOR_PROMPT if cli == "gemini" else UNIFIED_PROMPT
    return await run_cli_agent(prompt, diff, cli)
