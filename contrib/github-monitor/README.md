# GitHub Issue Monitor

Polls GitHub repos for issue activity from configured users and sends swarm wake messages when new activity is detected. Designed to run on cron every 5 minutes on each agent's machine.

## Prerequisites

- Python 3.10+
- PyYAML (`pip install pyyaml`)
- `gh` CLI authenticated (`gh auth login`)
- `swarm` CLI in PATH (via ASP venv)

## Files

| File | Purpose |
|------|---------|
| `monitor.py` | Main polling script |
| `config.yaml` | Repos, users, tiers, and swarm settings |
| `README.md` | This file |

## Configuration

Edit `config.yaml` to add or remove repos, users, and notification targets.

### User Tiers

| Tier | Behavior | Example |
|------|----------|---------|
| `principal` | Full autonomy -- execute without waiting for input | Dan, Martin |
| `team` | Normal workflow -- route and delegate as usual | Sage, Nexus, Kelvin |
| `external` | Triage -- assess and route to team member | Future collaborators |

### Adding a New Repo

```yaml
repos:
  - owner/repo-name  # just add a line
```

### Adding a New User

Add the GitHub username under the appropriate tier:

```yaml
users:
  team:
    - new-username
```

## Usage

```bash
# Normal run (cron calls this)
python3 monitor.py

# Dry run -- show what would be sent, don't actually send
python3 monitor.py --dry-run

# Use a custom config file
python3 monitor.py --config /path/to/config.yaml

# Reset state -- re-check all activity from scratch
python3 monitor.py --reset
```

## Cron Setup

Add to crontab (`crontab -e`):

```bash
# Run every 5 minutes
*/5 * * * * cd /root/projects/agent-swarm-protocol && source venv/bin/activate && python3 contrib/github-monitor/monitor.py >> ~/.github-monitor.log 2>&1
```

## State and Logs

| File | Location | Purpose |
|------|----------|---------|
| State | `~/.github-monitor-state.json` | Tracks last-seen event timestamps per repo |
| Log | `~/.github-monitor.log` | Activity and error log |

The state file prevents duplicate alerts. Delete it (or use `--reset`) to re-check all activity.

## How It Works

1. Reads `config.yaml` for repos, users, and swarm settings
2. Loads state from `~/.github-monitor-state.json`
3. For each monitored user, queries the GitHub Search Issues API for new activity
4. For each new event:
   - Determines user tier (principal/team/external)
   - Fetches the issue body or latest comment
   - Formats a wake message with tier-appropriate autonomy instructions
   - Sends via `swarm send` to all configured notification targets
5. Saves updated state
6. Logs all activity

### Rate Limits

The GitHub Search API allows 30 requests per minute for authenticated users. The script handles rate limiting gracefully by logging a warning and skipping the affected query.

### Deduplication

Events are tracked by a composite key of `{repo}#{issue_number}@{updated_at}`. The same issue at the same update timestamp is never alerted twice, even across multiple runs.

## Wake Message Format

Messages include the activity details and tier-specific instructions:

- **Principal**: Full autonomy directive -- execute completely without waiting
- **Team**: Normal workflow -- route through standard delegation
- **External**: Triage mode -- assess and route to team member

## Troubleshooting

### No messages being sent

1. Check `gh auth status` -- must be authenticated
2. Check `swarm send --help` -- must be in PATH
3. Run with `--dry-run` to see what would be sent
4. Check `~/.github-monitor.log` for errors

### Duplicate messages

The state file (`~/.github-monitor-state.json`) prevents duplicates. If you see duplicates, the state file may have been corrupted or deleted. Run `--reset` to rebuild.

### Rate limiting

If monitoring many repos and users, you may hit the 30 req/min search API limit. Reduce the number of monitored repos or increase the cron interval.
