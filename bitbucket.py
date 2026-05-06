import os
import re
import httpx
import logging

logger = logging.getLogger(__name__)


def parse_pr_url(url: str) -> tuple[str, str, str]:
    logger.debug("Parsing PR URL: %s", url)
    match = re.search(
        r"bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)",
        url,
    )
    if not match:
        logger.error("Failed to parse PR URL: %s", url)
        raise ValueError(f"Cannot parse Bitbucket PR URL: {url!r}")
    return match.group(1), match.group(2), match.group(3)


def connect() -> dict:
    logger.debug("Resolving Bitbucket credentials")
    token = os.getenv("BITBUCKET_TOKEN")
    email = os.getenv("BITBUCKET_EMAIL")
    user = os.getenv("BITBUCKET_USER")
    app_password = os.getenv("BITBUCKET_APP_PASSWORD")

    if token and email:
        logger.info("Using Token-based authentication")
        return {"strategy": "token", "credentials": (email, token)}
    if user and app_password:
        logger.info("Using App Password-based authentication")
        return {"strategy": "app_password", "credentials": (user, app_password)}
    
    logger.error("Bitbucket credentials missing in environment")
    raise RuntimeError(
        "Bitbucket credentials missing.\n"
        "  Option A (API Token):    set BITBUCKET_EMAIL + BITBUCKET_TOKEN\n"
        "  Option B (App Password): set BITBUCKET_USER + BITBUCKET_APP_PASSWORD"
    )


def fetch_diff(pr_url: str, auth: dict) -> str:
    workspace, repo_slug, pr_id = parse_pr_url(pr_url)
    endpoint = (
        f"https://api.bitbucket.org/2.0/repositories"
        f"/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
    )
    logger.info("Fetching diff for PR #%s in %s/%s", pr_id, workspace, repo_slug)
    with httpx.Client() as client:
        response = client.get(
            endpoint, auth=auth["credentials"], follow_redirects=True
        )
    
    if response.status_code == 401:
        logger.error("Bitbucket authentication failed (401)")
        raise RuntimeError("Bitbucket auth failed (401). Check your credentials.")
    if response.status_code == 403:
        logger.error("Access denied (403) to %s/%s", workspace, repo_slug)
        raise RuntimeError(
            f"Access denied (403) to {workspace}/{repo_slug}. "
            "Make sure the token has 'Pull Requests: Read' scope."
        )
    if response.status_code == 404:
        logger.error("PR #%s not found in %s/%s (404)", pr_id, workspace, repo_slug)
        raise RuntimeError(
            f"PR #{pr_id} not found in {workspace}/{repo_slug} (404). "
            "Check the URL and repository name."
        )
    response.raise_for_status()
    logger.debug("Successfully fetched diff (%d bytes)", len(response.text))
    return response.text
