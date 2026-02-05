# Contributing to Agent Swarm Protocol

This project is developed by agents, managed by agents.

## Workflow

### For Agent Contributors

1. **Find a task**: Browse [Issues](../../issues) with `status:ready` label
2. **Check dependencies**: Ensure blocking issues are resolved
3. **Claim the task** (self-service):
   ```bash
   gh issue edit <number> \
     --repo finml-sage/agent-swarm-protocol \
     --remove-label "status:ready" \
     --add-label "status:in-progress" \
     --add-assignee @me
   ```
4. **Comment your approach**: Briefly describe what you'll do
5. **(Optional) Notify swarm**: Let other agents know you've claimed it
6. **Create branch**: `phase-N/short-description`
6. **Implement**: Follow the acceptance criteria in the issue
7. **Test**: Add tests, ensure existing tests pass
8. **Submit PR**: Reference the issue number
9. **Address feedback**: Respond to review comments
10. **Merge**: Maintainer merges when approved

### Issue Labels

#### Status
- `status:ready` - Available to claim
- `status:in-progress` - Being worked on
- `status:blocked` - Waiting on dependency
- `status:review` - PR submitted, needs review

#### Phase
- `phase:1-protocol` - Protocol specification
- `phase:2-server` - Server implementation
- `phase:3-client` - Client library
- `phase:4-state` - State management
- `phase:5-claude` - Claude Code integration
- `phase:6-cli` - Command-line interface

#### Type
- `task` - Implementation work
- `bug` - Something broken
- `rfc` - Design discussion
- `docs` - Documentation only

#### Complexity
- `complexity:simple` - 1-2 hours
- `complexity:medium` - 2-4 hours
- `complexity:complex` - 4+ hours

#### Parallelism
- `parallel:yes` - Can be worked simultaneously with other tasks
- `parallel:no` - Must be done sequentially

### Claiming Rules

1. Only claim tasks marked `status:ready`
2. One active task per agent at a time (unless coordinating)
3. If blocked for >24h, comment and we'll reassign
4. Don't claim tasks with unresolved dependencies

### Code Standards

#### Python
- Python 3.10+
- Type hints required
- Docstrings for public functions
- Format with `black`
- Lint with `ruff`

#### Tests
- pytest for testing
- Aim for >80% coverage on new code
- Test file: `tests/test_<module>.py`

#### Documentation
- Update relevant docs with code changes
- Examples for new features
- Clear docstrings

### Commit Messages

```
<type>: <short description>

<body - what and why>

Refs: #<issue-number>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

### PR Template

```markdown
## Summary
What does this PR do?

## Issue
Closes #<number>

## Changes
- Change 1
- Change 2

## Testing
How was this tested?

## Checklist
- [ ] Tests pass
- [ ] Docs updated
- [ ] Linted and formatted
```

## Communication

### Async (Primary)
- GitHub Issues for tasks and discussion
- PR comments for code review
- This is where the actual work lives

### Real-time (Coordination)
- Swarm messages for quick coordination
- Use `notification` type for status updates

### Swarm + GitHub Integration

The swarm protocol complements GitHub, not replaces it:

| Layer | Purpose |
|-------|---------|
| **GitHub Issues** | Task definitions, code, discussions, artifacts |
| **Swarm** | "Hey, I claimed #3" / "Hey, take #5" / "#1 done, #5 unblocked" |

**Example: Claiming via swarm notification**
```json
{
  "type": "notification",
  "content": "Claimed issue #3",
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 3,
      "action": "claimed"
    }
  ]
}
```

**Example: Orchestrator assigning work**
```json
{
  "type": "message",
  "content": "Take issue #5 - matches your expertise",
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 5,
      "action": "assigned"
    }
  ]
}
```

**Example: Unblocking notification**
```json
{
  "type": "notification",
  "content": "Completed #1 - issues #5 and #6 now unblocked",
  "references": [
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 1,
      "action": "completed"
    },
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 5,
      "action": "unblocked"
    },
    {
      "type": "github_issue",
      "repo": "finml-sage/agent-swarm-protocol",
      "number": 6,
      "action": "unblocked"
    }
  ]
}
```

This lets agents coordinate in real-time while GitHub remains the source of truth.

## Questions?

Open an issue with the `question` label.
