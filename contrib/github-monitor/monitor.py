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
import fcntl
import json
import logging
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from urllib.parse import urlencode

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

STATE_FILE = Path.home() / ".github-monitor-state.json"
LOCK_FILE = Path.home() / ".github-monitor.lock"
LOG_FILE = Path.home() / ".github-monitor.log"
DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"
STATE_TTL_DAYS = 7

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
    """Load and validate the YAML configuration file.

    Supports two repos formats:
    - New (dict): per-repo coordinator mapping
    - Legacy (list of strings): uses default_coordinator fallback
    """
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
    # Validate repos format
    repos = config["repos"]
    # Collect all known agent IDs from the users config for coordinator validation
    known_agents: set[str] = set()
    users_cfg = config.get("users", {})
    for tier in ("principal", "team", "external"):
        tier_list = users_cfg.get(tier, [])
        if isinstance(tier_list, list):
            known_agents.update(tier_list)
    if isinstance(repos, dict):
        for repo_name, repo_cfg in repos.items():
            if isinstance(repo_cfg, dict) and "coordinator" not in repo_cfg:
                raise ValueError(
                    f"Repo '{repo_name}' is missing 'coordinator' field"
                )
            if isinstance(repo_cfg, dict) and known_agents:
                coord = repo_cfg.get("coordinator", "")
                if coord and coord not in known_agents:
                    logging.warning(
                        "Repo '%s' coordinator '%s' is not a known agent ID "
                        "in the users config",
                        repo_name,
                        coord,
                    )
    elif not isinstance(repos, list):
        raise ValueError("'repos' must be a list or dict")
    # Validate default_coordinator if present
    default_coord = config.get("default_coordinator", "")
    if default_coord and known_agents and default_coord not in known_agents:
        logging.warning(
            "default_coordinator '%s' is not a known agent ID "
            "in the users config",
            default_coord,
        )
    return config


def load_state() -> dict:
    """Load monitor state from JSON file."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_check": None, "seen_events": {}}


def prune_old_events(state: dict) -> int:
    """Remove seen_events older than STATE_TTL_DAYS.

    Event keys are formatted as 'repo#number@updated_at' where updated_at
    is an ISO 8601 timestamp. Returns the number of pruned entries.
    """
    seen = state.get("seen_events", {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=STATE_TTL_DAYS)
    stale_keys = []
    for key, updated_at in seen.items():
        try:
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if ts < cutoff:
                stale_keys.append(key)
        except (ValueError, TypeError, AttributeError):
            stale_keys.append(key)
    for key in stale_keys:
        del seen[key]
    return len(stale_keys)


def save_state(state: dict) -> None:
    """Persist monitor state to JSON file.

    Prunes events older than STATE_TTL_DAYS before writing.
    """
    pruned = prune_old_events(state)
    if pruned > 0:
        logger.info("Pruned %d stale events from state", pruned)
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


def get_repo_list(config: dict) -> list[str]:
    """Extract the list of repo name strings from config.

    Handles both new (dict) and legacy (list) formats.
    """
    repos = config["repos"]
    if isinstance(repos, dict):
        return list(repos.keys())
    return list(repos)


def get_coordinator(repo: str, config: dict) -> str:
    """Look up the coordinator agent for a given repo.

    For dict-style repos config, returns the coordinator field.
    For legacy list-style repos or missing entries, falls back to
    default_coordinator.

    Raises ValueError if no coordinator can be determined.
    """
    repos = config["repos"]
    default = config.get("default_coordinator")

    if isinstance(repos, dict):
        repo_cfg = repos.get(repo)
        if isinstance(repo_cfg, dict):
            return repo_cfg["coordinator"]
        # Plain string value or None -- fall back to default
        if default:
            return default
        raise ValueError(
            f"No coordinator for repo '{repo}' and no default_coordinator set"
        )

    # Legacy list format
    if default:
        return default
    raise ValueError(
        f"Legacy repo list format requires 'default_coordinator' in config"
    )


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


def fetch_latest_comment(
    repo: str, issue_number: int, user: str | None = None,
) -> dict | None:
    """Fetch the most recent comment on an issue, optionally by a specific user.

    The issue-level comments endpoint does NOT support sort/direction params.
    Comments are always returned in chronological order (oldest first).
    We fetch up to 100 and take the last one matching the target user.
    """
    try:
        comments = gh_api(
            f"/repos/{repo}/issues/{issue_number}/comments",
            params={"per_page": "100"},
        )
        if not comments or not isinstance(comments, list):
            return None
        if user:
            user_comments = [
                c for c in comments
                if c.get("user", {}).get("login") == user
            ]
            return user_comments[-1] if user_comments else None
        return comments[-1]
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
    """Format the wake message based on user tier.

    Includes task chain management instructions for principal and team
    tiers so the coordinator knows to decompose, delegate, and track
    until all agents confirm completion.
    """
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
            "- Report completion via swarm message when done\n"
            "\n"
            "TASK CHAIN MANAGEMENT:\n"
            "- You are the coordinator for this directive\n"
            "- Decompose the task and delegate subtasks to other agents "
            "via swarm\n"
            "- Do NOT require Dan or any user to participate -- handle "
            "entirely within the team\n"
            "- Track progress on the GitHub issue with status comments\n"
            "- The task chain stays OPEN until ALL involved agents confirm "
            "completion via swarm message\n"
            "- Only close when every agent who worked on a subtask confirms: "
            '"my piece is done" or "blocked at [reason]"\n'
            "- If you need another agent's help, send them a specific "
            "subtask via swarm -- do not broadcast"
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
            "- Verify before reporting complete\n"
            "\n"
            "TASK CHAIN MANAGEMENT:\n"
            "- You are the coordinator for this activity\n"
            "- If this requires work from other agents, delegate specific "
            "subtasks via swarm\n"
            "- Handle within the team -- do not escalate to Dan unless a "
            "guardrail fires\n"
            "- Keep the task open until all involved agents confirm "
            "completion via swarm"
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

    If the issue was recently commented on, fetch the latest comment by
    the target user. Otherwise use the issue body already present in the
    search result to avoid a redundant API call.
    """
    issue_number = issue["number"]
    comments_count = issue.get("comments", 0)

    if comments_count > 0:
        comment = fetch_latest_comment(repo, issue_number, user=user)
        if comment:
            body = comment.get("body", "")
            if body:
                return f"[Comment by {user}]\n{body}"

    issue_body = issue.get("body")
    if issue_body:
        return issue_body

    return "(No content available)"


def process_repo(
    repo: str,
    coordinator: str,
    users: list[tuple[str, str]],
    state: dict,
    swarm_config: dict,
    dry_run: bool,
) -> int:
    """Process a single repo, sending wake messages to its coordinator.

    Each repo has a single designated coordinator. Only that agent
    receives the wake message -- no broadcast. The coordinator is
    responsible for decomposing and delegating to other agents via swarm.

    Returns the number of new events found.
    """
    seen = state.setdefault("seen_events", {})
    last_check = state.get("last_check")
    swarm_id = swarm_config["swarm_id"]
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

            # Don't wake the coordinator about their own activity
            if coordinator != user:
                send_wake_message(
                    swarm_id, coordinator, message, dry_run=dry_run,
                )

            seen[event_key] = updated_at
            new_events += 1
            logger.info(
                "New activity: %s#%d by %s (%s tier) -> coordinator %s",
                repo,
                issue_number,
                user,
                tier,
                coordinator,
            )

    return new_events


def acquire_lock() -> TextIOWrapper:
    """Acquire an exclusive lockfile to prevent overlapping cron runs.

    Returns the file object on success.
    Raises SystemExit if the lock is already held by another process.
    """
    fd = open(LOCK_FILE, "w")  # noqa: SIM115
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.warning("Another monitor instance is already running, exiting")
        fd.close()
        sys.exit(0)
    return fd


def release_lock(fd: TextIOWrapper) -> None:
    """Release the lockfile."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def run(config_path: Path, dry_run: bool = False, seed: bool = False) -> None:
    """Main monitor loop: check all repos and send wake messages."""
    lock_fd = acquire_lock()
    try:
        _run_inner(config_path, dry_run=dry_run, seed=seed)
    finally:
        release_lock(lock_fd)


def _run_inner(
    config_path: Path, dry_run: bool = False, seed: bool = False,
) -> None:
    """Core monitor logic, called under lock."""
    config = load_config(config_path)
    state = load_state()
    repo_names = get_repo_list(config)
    users = get_monitored_users(config["users"])
    swarm_config = config["swarm"]

    if not users:
        logger.warning("No users configured to monitor")
        return

    # In seed mode, scan all repos but skip sending — just populate state
    effective_dry_run = dry_run or seed

    total_events = 0
    for repo in repo_names:
        try:
            coordinator = get_coordinator(repo, config)
            events = process_repo(
                repo, coordinator, users, state, swarm_config,
                effective_dry_run,
            )
            total_events += events
        except Exception:
            logger.exception("Error processing repo %s", repo)
            continue

    if seed:
        # Seed mode: save state without having sent anything
        save_state(state)
        logger.info("Seed complete: %d events recorded, no messages sent", total_events)
    elif not dry_run:
        save_state(state)

    logger.info(
        "Monitor complete: %d repos checked, %d new events",
        len(repo_names),
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
        "--seed",
        action="store_true",
        help="Scan all repos and save state without sending any messages. "
        "Run this once before enabling cron to avoid flooding with historical events.",
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
        run(args.config, dry_run=args.dry_run, seed=args.seed)
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
