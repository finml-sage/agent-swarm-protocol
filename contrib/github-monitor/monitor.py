#!/usr/bin/env python3
"""GitHub issue monitor that sends swarm wake messages on activity.

Polls GitHub repos for issue activity from configured users and sends
wake messages via the swarm CLI when new activity is detected.

Usage:
    python3 monitor.py              # Normal run (cron calls this)
    python3 monitor.py --dry-run    # Show what would be sent
    python3 monitor.py --config /path/to/config.yaml
    python3 monitor.py --reset      # Reset state, re-check everything
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

STATE_FILE = Path.home() / ".github-monitor-state.json"
LOG_FILE = Path.home() / ".github-monitor.log"
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"

logger = logging.getLogger("github-monitor")


def setup_logging() -> None:
    """Configure logging to file and stderr."""
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)


def load_config(config_path: Path) -> dict:
    """Load and validate the YAML configuration file."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    if not config:
        raise ValueError(f"Config file is empty: {config_path}")
    for key in ("repos", "users", "swarm"):
        if key not in config:
            raise ValueError(f"Missing required config section: {key}")
    if "swarm_id" not in config["swarm"]:
        raise ValueError("Missing swarm.swarm_id in config")
    if "notify" not in config["swarm"]:
        raise ValueError("Missing swarm.notify in config")
    return config


def load_state() -> dict:
    """Load monitor state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_check": None, "seen_events": {}}


def save_state(state: dict) -> None:
    """Persist monitor state to JSON file."""
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def reset_state() -> None:
    """Delete the state file to force a full re-check."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        logger.info("State file deleted: %s", STATE_FILE)
    else:
        logger.info("No state file to reset")


def get_user_tier(username: str, users_config: dict) -> str | None:
    """Determine the tier for a given GitHub username."""
    for tier in ("principal", "team", "external"):
        tier_users = users_config.get(tier, [])
        if tier_users and username in tier_users:
            return tier
    return None


def gh_api(endpoint: str, params: dict | None = None) -> dict | list:
    """Call the GitHub API via the gh CLI.

    Uses URL query parameters for GET requests (required by Search API).

    Raises subprocess.CalledProcessError on non-zero exit.
    Raises json.JSONDecodeError on malformed response.
    """
    url = endpoint
    if params:
        url = f"{endpoint}?{urlencode(params)}"
    cmd = ["gh", "api", url]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def build_search_query(
    user: str,
    repo: str,
    since: str | None,
) -> str:
    """Build a GitHub Search Issues query string."""
    parts = [
        f"involves:{user}",
        f"repo:{repo}",
        "is:issue",
    ]
    if since:
        parts.append(f"updated:>{since}")
    return " ".join(parts)


def search_issues(
    user: str,
    repo: str,
    since: str | None,
) -> list[dict]:
    """Search for issues involving a user in a repo since a given time."""
    query = build_search_query(user, repo, since)
    try:
        data = gh_api(
            "/search/issues",
            params={"q": query, "sort": "updated", "per_page": "30"},
        )
    except subprocess.CalledProcessError as exc:
        if "rate limit" in (exc.stderr or "").lower():
            logger.warning("Rate limited on search API, skipping: %s", query)
            return []
        logger.error("GitHub API error for query '%s': %s", query, exc.stderr)
        return []
    except subprocess.TimeoutExpired:
        logger.warning("Timeout searching: %s", query)
        return []

    if isinstance(data, dict) and "items" in data:
        return data["items"]
    return []


def fetch_issue_details(repo: str, issue_number: int) -> dict | None:
    """Fetch full issue details including body."""
    try:
        return gh_api(f"/repos/{repo}/issues/{issue_number}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Failed to fetch %s#%d: %s", repo, issue_number, exc)
        return None


def fetch_latest_comment(repo: str, issue_number: int) -> dict | None:
    """Fetch the most recent comment on an issue."""
    try:
        comments = gh_api(
            f"/repos/{repo}/issues/{issue_number}/comments",
            params={"per_page": "1", "sort": "created", "direction": "desc"},
        )
        if comments and isinstance(comments, list):
            return comments[0]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error(
            "Failed to fetch comments for %s#%d: %s",
            repo,
            issue_number,
            exc,
        )
    return None


def format_wake_message(
    tier: str,
    username: str,
    repo: str,
    issue_number: int,
    issue_title: str,
    content: str,
) -> str:
    """Format the wake message based on user tier."""
    if tier == "principal":
        header = (
            f'PRINCIPAL DIRECTIVE from {username} on '
            f'{repo}#{issue_number}: "{issue_title}"'
        )
        footer = (
            "---\n"
            "AUTONOMY LEVEL: FULL\n"
            "- Execute this task fully and autonomously\n"
            "- Do NOT stop early or wait for input\n"
            "- Do NOT ask clarifying questions -- make reasonable decisions "
            "and proceed\n"
            "- Complete the full task chain: research -> plan -> implement "
            "-> verify -> report\n"
            "- If blocked, find an alternative path before escalating\n"
            "- Only escalate if genuinely impossible (not merely uncertain)\n"
            "- Coordinate with team members as needed but do not wait for "
            "consensus to act\n"
            "- Report completion via swarm message when done"
        )
    elif tier == "team":
        header = (
            f'Team activity from {username} on '
            f'{repo}#{issue_number}: "{issue_title}"'
        )
        footer = (
            "---\n"
            "AUTONOMY LEVEL: NORMAL\n"
            "- Route through standard workflow\n"
            "- Delegate to appropriate specialists\n"
            "- Verify before reporting complete"
        )
    else:
        header = (
            f'External activity from {username} on '
            f'{repo}#{issue_number}: "{issue_title}"'
        )
        footer = (
            "---\n"
            "AUTONOMY LEVEL: TRIAGE\n"
            "- Assess the request\n"
            "- Route to appropriate team member\n"
            "- Do not execute without team review"
        )
    return f"{header}\n\n{content}\n\n{footer}"


def send_wake_message(
    swarm_id: str,
    target: str,
    message: str,
    dry_run: bool = False,
) -> bool:
    """Send a wake message via the swarm CLI.

    Returns True if the message was sent (or would be sent in dry-run).
    """
    if dry_run:
        logger.info("[DRY RUN] Would send to %s:\n%s", target, message)
        return True

    cmd = [
        "swarm",
        "send",
        "--swarm",
        swarm_id,
        "--to",
        target,
        "--message",
        message,
    ]
    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        logger.info("Sent wake message to %s", target)
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to send to %s: %s", target, exc.stderr)
        return False
    except subprocess.TimeoutExpired:
        logger.error("Timeout sending to %s", target)
        return False


def get_monitored_users(users_config: dict) -> list[tuple[str, str]]:
    """Extract all (username, tier) pairs from the users config."""
    result = []
    for tier in ("principal", "team", "external"):
        tier_users = users_config.get(tier, [])
        if tier_users:
            for user in tier_users:
                result.append((user, tier))
    return result


def make_event_key(repo: str, issue_number: int, updated_at: str) -> str:
    """Create a unique key for a specific issue update event."""
    return f"{repo}#{issue_number}@{updated_at}"


def determine_content(
    repo: str,
    issue: dict,
    user: str,
) -> str:
    """Determine the relevant content to include in the wake message.

    If the issue was recently commented on, fetch the latest comment.
    Otherwise use the issue body.
    """
    issue_number = issue["number"]
    comments_count = issue.get("comments", 0)

    if comments_count > 0:
        comment = fetch_latest_comment(repo, issue_number)
        if comment and comment.get("user", {}).get("login") == user:
            body = comment.get("body", "")
            if body:
                return f"[Comment by {user}]\n{body}"

    details = fetch_issue_details(repo, issue_number)
    if details and details.get("body"):
        return details["body"]

    return "(No content available)"


def process_repo(
    repo: str,
    users: list[tuple[str, str]],
    state: dict,
    swarm_config: dict,
    dry_run: bool,
) -> int:
    """Process a single repo for all monitored users.

    Returns the number of new events found.
    """
    seen = state.setdefault("seen_events", {})
    last_check = state.get("last_check")
    swarm_id = swarm_config["swarm_id"]
    notify_targets = swarm_config["notify"]
    new_events = 0

    for user, tier in users:
        issues = search_issues(user, repo, last_check)

        for issue in issues:
            issue_number = issue["number"]
            updated_at = issue.get("updated_at", "")
            event_key = make_event_key(repo, issue_number, updated_at)

            if event_key in seen:
                continue

            issue_title = issue.get("title", "(untitled)")
            content = determine_content(repo, issue, user)
            message = format_wake_message(
                tier, user, repo, issue_number, issue_title, content,
            )

            for target in notify_targets:
                if target == user:
                    continue
                send_wake_message(swarm_id, target, message, dry_run=dry_run)

            seen[event_key] = updated_at
            new_events += 1
            logger.info(
                "New activity: %s#%d by %s (%s tier)",
                repo,
                issue_number,
                user,
                tier,
            )

    return new_events


def run(config_path: Path, dry_run: bool = False) -> None:
    """Main monitor loop: check all repos and send wake messages."""
    config = load_config(config_path)
    state = load_state()
    repos = config["repos"]
    users = get_monitored_users(config["users"])
    swarm_config = config["swarm"]

    if not users:
        logger.warning("No users configured to monitor")
        return

    total_events = 0
    for repo in repos:
        try:
            events = process_repo(repo, users, state, swarm_config, dry_run)
            total_events += events
        except Exception:
            logger.exception("Error processing repo %s", repo)
            continue

    if not dry_run:
        save_state(state)

    logger.info(
        "Monitor complete: %d repos checked, %d new events",
        len(repos),
        total_events,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Monitor GitHub repos for issue activity and send swarm "
        "wake messages.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to config.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be sent without actually sending",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset state file and re-check everything",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Entry point."""
    setup_logging()
    args = parse_args()

    if args.reset:
        reset_state()
        logger.info("State reset. Next run will check all activity.")
        return

    try:
        run(args.config, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except ValueError as exc:
        logger.error("Config error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
