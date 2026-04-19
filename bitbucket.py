import os
import re
import httpx


def parse_pr_url(url: str) -> tuple[str, str, str]:
    match = re.search(
        r"bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)",
        url,
    )
    if not match:
        raise ValueError(f"Cannot parse Bitbucket PR URL: {url!r}")
    return match.group(1), match.group(2), match.group(3)


def fetch_diff(pr_url: str) -> str:
    workspace, repo_slug, pr_id = parse_pr_url(pr_url)
    endpoint = (
        f"https://api.bitbucket.org/2.0/repositories"
        f"/{workspace}/{repo_slug}/pullrequests/{pr_id}/diff"
    )

    # Bitbucket Cloud API Token → Basic auth with email:token
    # App Password → Basic auth with bitbucket_username:app_password
    token = os.getenv("BITBUCKET_TOKEN")
    email = os.getenv("BITBUCKET_EMAIL")
    user = os.getenv("BITBUCKET_USER")
    app_password = os.getenv("BITBUCKET_APP_PASSWORD")

    if token and email:
        auth = (email, token)
    elif user and app_password:
        auth = (user, app_password)
    else:
        raise RuntimeError(
            "Bitbucket credentials missing.\n"
            "  Option A (API Token):    set BITBUCKET_EMAIL + BITBUCKET_TOKEN\n"
            "  Option B (App Password): set BITBUCKET_USER + BITBUCKET_APP_PASSWORD"
        )

    headers = {}

    with httpx.Client() as client:
        response = client.get(
            endpoint, headers=headers, auth=auth, follow_redirects=True
        )

    if response.status_code == 401:
        raise RuntimeError("Bitbucket auth failed (401). Check your credentials.")
    if response.status_code == 403:
        raise RuntimeError(
            f"Access denied (403) to {workspace}/{repo_slug}. "
            "Make sure the App Password has 'Pull Requests: Read' scope."
        )
    if response.status_code == 404:
        raise RuntimeError(
            f"PR #{pr_id} not found in {workspace}/{repo_slug} (404). "
            "Check the URL and repository name."
        )

    response.raise_for_status()
    return response.text
