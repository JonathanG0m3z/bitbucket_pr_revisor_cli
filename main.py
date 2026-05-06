import json
import sys
import os
import argparse
import logging
from dotenv import load_dotenv
from graph import app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("bitbucket_pr_revisor")


def print_separator(title: str) -> None:
    print("\n" + "═" * 40)
    print(f" {title}")
    print("═" * 40)


def validate_env() -> None:
    """Validates that required environment variables are set."""
    missing = []
    
    # Check Bitbucket credentials
    has_token = os.getenv("BITBUCKET_TOKEN") and os.getenv("BITBUCKET_EMAIL")
    has_app_pass = os.getenv("BITBUCKET_USER") and os.getenv("BITBUCKET_APP_PASSWORD")
    
    if not (has_token or has_app_pass):
        missing.append("Bitbucket Credentials (BITBUCKET_TOKEN+BITBUCKET_EMAIL or BITBUCKET_USER+BITBUCKET_APP_PASSWORD)")
    
    if missing:
        print("Missing required environment variables:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Bitbucket PR Revisor CLI")
    parser.add_argument("pr_url", help="The URL of the Bitbucket Pull Request")
    parser.add_argument("--cli", help="Override the CLI backend (claude, codex, gemini)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        os.environ["DEBUG_CLI"] = "1"

    validate_env()

    pr_url = args.pr_url
    cli = args.cli or os.getenv("CLI", "claude")
    
    if cli not in ("claude", "codex", "gemini"):
        print(f"Error: CLI={cli!r} is not valid. Use: claude, codex, gemini")
        sys.exit(1)

    # Set the CLI in environment so the graph nodes can see it
    os.environ["CLI"] = cli

    try:
        logger.info("Starting review for PR: %s using CLI: %s", pr_url, cli)
        print(f"Reviewing PR: {pr_url}...")
        
        result = app.invoke({"pr_url": pr_url})

        raw = result.get("report", "")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse report as JSON. Raw output below.")
            print_separator("RAW AGENT OUTPUT")
            print(raw)
            return

        score = data.get("score", "N/A")
        severity = data.get("overall_severity", "unknown").upper()
        print_separator(f"PR REVIEW  —  Score: {score}/10  |  Severity: {severity}")

        for section in ("security", "performance", "style"):
            if section not in data:
                continue
            s = data[section]
            print_separator(f"{section.upper()} REVIEW")
            print(s.get("summary", ""))
            for issue in s.get("issues", []):
                prefix = f"  Line {issue['line']}: " if issue.get("line") else "  "
                print(f"{prefix}[{issue.get('type', section)}] {issue.get('description', '')}")

        actions = data.get("critical_actions", []) or data.get("top_actions", [])
        if actions:
            print_separator("CRITICAL ACTIONS")
            for i, action in enumerate(actions, 1):
                print(f"{i}. {action}")

        summary = data.get("executive_summary", "")
        if summary:
            print_separator("EXECUTIVE SUMMARY")
            print(summary)

    except RuntimeError as e:
        logger.error("Runtime error: %s", e)
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error occurred")
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
