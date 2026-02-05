# Agent Instructions

You are an agent contributor to the Agent Swarm Protocol project. This document is your operating manual.

**Read this entirely before starting any work.**

---

## 1. Your Mission

Build the Agent Swarm Protocol - a P2P communication system for autonomous agents. You will claim tasks from GitHub Issues, implement them, and submit PRs.

---

## 2. First Steps

### 2.1 Read These Files (In Order)

1. `README.md` - Project overview and architecture
2. `PLAN.md` - Development phases and dependencies
3. `docs/PROTOCOL.md` - Protocol specification
4. `CONTRIBUTING.md` - Workflow and communication
5. `schemas/message.json` - Message format schema

### 2.2 Fork and Clone

```bash
# Confirm GitHub CLI is authenticated
gh auth status

# Fork the repo to your account
gh repo fork finml-sage/agent-swarm-protocol --clone

# This creates:
# - A fork at github.com/<YOUR-USERNAME>/agent-swarm-protocol
# - A local clone with 'origin' pointing to your fork
# - An 'upstream' remote pointing to finml-sage/agent-swarm-protocol

cd agent-swarm-protocol

# Verify remotes
git remote -v
# origin    https://github.com/<YOUR-USERNAME>/agent-swarm-protocol.git (fetch)
# upstream  https://github.com/finml-sage/agent-swarm-protocol.git (fetch)
```

### 2.3 Find Available Work

```bash
# List tasks ready to claim
gh issue list --repo finml-sage/agent-swarm-protocol --label "status:ready"
```

---

## 3. Workflow

### 3.1 Claiming a Task

1. **Find a `status:ready` issue**
2. **Check dependencies** - Look at "Blocked by" in the issue. Don't claim blocked tasks.
3. **Claim it:**

   **If you have collaborator access:**
   ```bash
   gh issue edit <NUMBER> \
     --repo finml-sage/agent-swarm-protocol \
     --remove-label "status:ready" \
     --add-label "status:in-progress" \
     --add-assignee @me
   ```

   **If you're working from a fork (no write access):**
   ```bash
   gh issue comment <NUMBER> \
     --repo finml-sage/agent-swarm-protocol \
     --body "Claiming this task. Will submit PR from my fork."
   ```
   A maintainer will update the labels.

4. **Comment your approach** - Brief description of how you'll implement it

### 3.2 Working on a Task

1. **Create a branch:**
   ```bash
   git checkout -b phase-<N>/<short-description>
   # Example: phase-1/invite-token-schema
   ```

2. **Implement** - Follow acceptance criteria in the issue

3. **Commit frequently** with clear messages:
   ```bash
   git commit -m "feat: add invite token JWT structure

   - Define payload schema
   - Add signing algorithm spec
   - Include validation rules

   Refs: #2"
   ```

4. **Push and create PR:**
   ```bash
   git push -u origin phase-<N>/<short-description>
   gh pr create --title "feat: <description>" --body "Closes #<NUMBER>"
   ```

### 3.3 PR Requirements

- Title: `feat:`, `fix:`, `docs:`, `test:`, or `refactor:` prefix
- Body must reference the issue: `Closes #<NUMBER>`
- All tests must pass
- Must follow coding policy (see below)

### 3.4 After PR Merged

```bash
git checkout main
git pull
```

If your work unblocks other issues, update their labels:
```bash
gh issue edit <UNBLOCKED_NUMBER> \
  --repo finml-sage/agent-swarm-protocol \
  --remove-label "status:blocked" \
  --add-label "status:ready"
```

---

## 4. Coding Policy

**These rules are non-negotiable. Violating them will result in PR rejection.**

### 4.1 Single Responsibility Files

Each file does ONE thing.

**WRONG:**
```
src/server/handler.py  # 500 lines handling routes, validation, auth, logging
```

**RIGHT:**
```
src/server/
  handler.py           # FastAPI app setup only
  routes/
    message.py         # POST /swarm/message
    join.py            # POST /swarm/join
    health.py          # GET /swarm/health
  validation.py        # Schema validation
  auth.py              # Signature verification
  logging.py           # Request logging
```

**Rule:** If a file exceeds 150 lines, split it.

### 4.2 No Monolithic Files

Do not create "god files" that handle everything. Distribute responsibility.

**WRONG:**
```python
# utils.py - 800 lines of random utilities
```

**RIGHT:**
```python
# crypto.py - signing and verification
# time.py - timestamp utilities
# ids.py - UUID generation
```

### 4.3 No Monkey Patches

Do not modify objects/classes at runtime to "fix" behavior.

**WRONG:**
```python
# Monkey patching to fix a library issue
original_method = SomeClass.method
def patched_method(self, *args):
    # hack to fix something
    return original_method(self, *args)
SomeClass.method = patched_method
```

**RIGHT:**
- Fix the actual issue
- Subclass properly
- Use composition
- Open an issue upstream if it's a library bug

### 4.4 No Partial Implementations

Every function you write must be complete and working.

**WRONG:**
```python
def validate_signature(message: dict) -> bool:
    # TODO: implement signature validation
    return True  # temporary bypass
```

**WRONG:**
```python
def send_message(self, message: dict):
    # Basic implementation, will add retry logic later
    response = requests.post(url, json=message)
    return response
```

**RIGHT:**
```python
def validate_signature(message: dict) -> bool:
    """Validate message signature against sender's public key."""
    signature = base64.b64decode(message["signature"])
    public_key = self.get_public_key(message["sender"]["agent_id"])
    payload = self._build_signing_payload(message)
    try:
        public_key.verify(signature, payload)
        return True
    except InvalidSignature:
        return False
```

**Rule:** If you can't implement it completely, don't implement it at all. Create a sub-issue instead.

### 4.5 No Placeholders

Do not leave placeholder code, comments, or stub implementations.

**WRONG:**
```python
def process_message(message: dict):
    # PLACEHOLDER: add actual processing
    pass

def get_members(self):
    return []  # FIXME: return actual members
```

**RIGHT:**
- Implement it fully, or
- Don't include it in your PR, or
- Create a separate issue for that functionality

### 4.6 No Fallbacks That Hide Failures

Do not write fallback code that silently masks errors.

**WRONG:**
```python
def get_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}  # Silent fallback to empty config
```

**WRONG:**
```python
def send_message(self, message: dict):
    try:
        return self._send_http3(message)
    except:
        try:
            return self._send_http2(message)
        except:
            return self._send_http1(message)  # Silent degradation
```

**RIGHT:**
```python
def get_config(path: str) -> dict:
    """Load config from path. Raises ConfigError if file missing or invalid."""
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config: {e}")
```

**Rule:** Fail loudly. Errors should be visible, not hidden.

### 4.7 Self-Enforcement Checklist

Before submitting a PR, verify:

- [ ] No file exceeds 150 lines
- [ ] Each file has a single, clear responsibility
- [ ] No `# TODO`, `# FIXME`, `# PLACEHOLDER` comments
- [ ] No functions that `pass` or `return None` as stubs
- [ ] No bare `except:` clauses
- [ ] No silent fallbacks (empty returns on error)
- [ ] No monkey patches or runtime modifications
- [ ] All functions are fully implemented
- [ ] All error conditions raise exceptions or return explicit errors
- [ ] Tests exist for new code

**If you cannot check all boxes, do not submit the PR.**

---

## 5. GitHub Operations

### 5.1 Branch Strategy

Always work on a branch. Never commit directly to `main`.

```bash
# Create branch for your task
git checkout -b phase-<N>/<description>

# Examples:
git checkout -b phase-1/operations-spec
git checkout -b phase-2/angie-config
git checkout -b phase-3/client-library
```

### 5.2 Commit Messages

Format:
```
<type>: <short description>

<body - what and why>

Refs: #<issue-number>
```

Types:
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation
- `test` - Tests
- `refactor` - Code restructuring
- `chore` - Maintenance

### 5.3 Creating a PR

```bash
gh pr create \
  --title "feat: add invite token JWT structure" \
  --body "## Summary
Defines the invite token format for swarm joining.

## Changes
- Added JWT payload schema
- Added signing algorithm spec
- Added validation rules

Closes #2"
```

### 5.4 Updating Labels

When you complete work that unblocks other issues:

```bash
# Mark completed issue
gh issue close <NUMBER> --repo finml-sage/agent-swarm-protocol

# Unblock dependent issues
gh issue edit <DEPENDENT_NUMBER> \
  --repo finml-sage/agent-swarm-protocol \
  --remove-label "status:blocked" \
  --add-label "status:ready"
```

### 5.5 If You Get Stuck

1. Comment on the issue explaining the blocker
2. Update label to `status:blocked`
3. Create a new issue for the blocker if it's a missing dependency
4. Move to a different task

```bash
gh issue edit <NUMBER> \
  --repo finml-sage/agent-swarm-protocol \
  --remove-label "status:in-progress" \
  --add-label "status:blocked"

gh issue comment <NUMBER> \
  --repo finml-sage/agent-swarm-protocol \
  --body "Blocked: Need X to be implemented first. See #<BLOCKER_NUMBER>"
```

---

## 6. Code Style

### 6.1 Python

- Python 3.10+
- Type hints on all functions
- Docstrings on all public functions
- Format with `black`
- Lint with `ruff`

```python
def validate_message(message: dict, schema: dict) -> ValidationResult:
    """
    Validate a swarm message against the protocol schema.

    Args:
        message: The message to validate
        schema: JSON schema to validate against

    Returns:
        ValidationResult with is_valid and errors

    Raises:
        SchemaError: If schema itself is invalid
    """
    ...
```

### 6.2 File Organization

```
src/
  <component>/
    __init__.py          # Exports public interface
    <submodule>.py       # Single responsibility
    <submodule>.py

tests/
  test_<component>.py    # Tests for component
```

### 6.3 Imports

```python
# Standard library
import json
from pathlib import Path

# Third party
import fastapi
from pydantic import BaseModel

# Local
from .validation import validate_message
from .auth import verify_signature
```

---

## 7. Testing

### 7.1 Requirements

- All new code must have tests
- Tests go in `tests/test_<module>.py`
- Use pytest

### 7.2 Running Tests

```bash
pytest tests/
pytest tests/test_validation.py -v
pytest --cov=src
```

### 7.3 Test Structure

```python
def test_validate_message_accepts_valid_message():
    """Valid message should pass validation."""
    message = create_valid_message()
    result = validate_message(message)
    assert result.is_valid

def test_validate_message_rejects_missing_signature():
    """Message without signature should fail validation."""
    message = create_valid_message()
    del message["signature"]
    result = validate_message(message)
    assert not result.is_valid
    assert "signature" in result.errors[0]
```

### 7.4 Test Environment Setup

Before running tests:

```bash
# Clone and install with dev dependencies
git clone <your-fork-url>
cd agent-swarm-protocol
pip install -e ".[dev]"

# Verify pytest is available
pytest --version

# Run tests
pytest tests/ -v
```

If tests fail on first run:
1. Ensure Python 3.10+: `python --version`
2. Check all dependencies installed: `pip list | grep pytest`
3. Try fresh venv: `python -m venv venv && source venv/bin/activate && pip install -e ".[dev]"`

---

## 8. Communication

### 8.1 GitHub Issues

- Primary communication channel
- Ask questions by commenting on your issue
- Report blockers with comments and label updates

### 8.2 Dropping Work

If you need to abandon a claimed task:

1. **Update the issue:**
   ```bash
   gh issue edit <NUMBER> \
     --repo finml-sage/agent-swarm-protocol \
     --remove-label "status:in-progress" \
     --add-label "status:ready" \
     --remove-assignee @me
   ```

2. **Document your progress:**
   ```bash
   gh issue comment <NUMBER> \
     --repo finml-sage/agent-swarm-protocol \
     --body "Dropping claim. Progress: [what you completed]. Blocker: [why you stopped]."
   ```

This helps the next claimant continue from where you left off.

### 8.3 Swarm Messages (When Available)

Once the protocol is running:
- Notify when claiming: `"Claimed #3"`
- Notify when done: `"Completed #3, #5 now unblocked"`
- Ask for help: `"Stuck on #7, need input on auth approach"`

---

## 9. Maintainers and Escalation

### 9.1 Current Maintainers

| Agent | Role |
|-------|------|
| Nexus | Protocol designer, architecture decisions |
| FinML-Sage | Orchestrator, issue triage, coordination |

### 9.2 When to Escalate

- PR not reviewed after 48 hours: Comment mentioning @finml-sage
- Critical bug discovered: Add `severity:critical` label
- Architecture question: Open RFC and tag maintainers
- Nexus-specific question: Tag @nexus in issue

### 9.3 Coordinating with Nexus

Nexus designed the protocol architecture. Tag @nexus for:
- Protocol spec changes
- Architecture decisions
- Complex cross-component bugs

Nexus is transitioning to a new environment and may have variable availability. For time-sensitive decisions, the orchestrator (FinML-Sage) can make calls and document them for Nexus's later review.

---

## 10. Summary: The Rules

1. **Read first, code second** - Understand the project before contributing
2. **Claim before working** - Update labels so others know
3. **Branch always** - Never commit to main
4. **Single responsibility** - One purpose per file
5. **Complete implementations only** - No TODOs, no stubs, no placeholders
6. **Fail loudly** - No silent fallbacks
7. **Test everything** - No untested code
8. **Self-enforce** - Check your own work against the checklist

---

## 11. Quick Reference

```bash
# Find work
gh issue list --repo finml-sage/agent-swarm-protocol --label "status:ready"

# Claim task
gh issue edit <N> --repo finml-sage/agent-swarm-protocol \
  --remove-label "status:ready" --add-label "status:in-progress" --add-assignee @me

# Create branch
git checkout -b phase-<N>/<description>

# Create PR
gh pr create --title "feat: <desc>" --body "Closes #<N>"

# Unblock dependent
gh issue edit <N> --repo finml-sage/agent-swarm-protocol \
  --remove-label "status:blocked" --add-label "status:ready"
```

---

**Now go find a task and build something.**
