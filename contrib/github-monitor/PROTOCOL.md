# GitHub Monitor: Principal Directive Wake Protocol

**Version**: 0.1.0
**Status**: Operational Specification
**Last Updated**: 2026-02-16

## 1. Purpose

This protocol defines how the GitHub issue monitoring system generates wake
messages for the agent swarm, with special handling for "principal directives"
-- activity from Dan (vantasnerdan) or Martin (mdurchschlag) that grants agents
full execution autonomy.

The core problem: not all GitHub activity deserves the same agent response.
An issue created by Dan should trigger complete autonomous execution. An issue
from an external contributor should trigger triage only. This protocol codifies
those distinctions.

## 2. User Tiers

### 2.1 Tier Definitions

| Tier | GitHub Users | Autonomy Level | Description |
|------|-------------|----------------|-------------|
| `principal` | `vantasnerdan`, `mdurchschlag` | Full | Execute completely without human approval |
| `team` | `finml-sage`, `nexus-marbell`, `mlops-kelvin` | Standard | Normal workflow with checkpoints |
| `external` | All others | Triage | Classify, summarize, notify -- do not execute |

### 2.2 Tier Lookup

User tier is resolved by GitHub username at the time the monitor detects
activity. The tier mapping is configuration, not code -- it lives in the
monitor's config file:

```json
{
  "user_tiers": {
    "principal": ["vantasnerdan", "mdurchschlag"],
    "team": ["finml-sage", "nexus-marbell", "mlops-kelvin"],
    "external": "*"
  }
}
```

The `"external"` tier is the default for any username not listed in
`principal` or `team`. Unknown users never receive autonomy above triage.

### 2.3 Tier Behavior Summary

**Principal** -- The agent treats the issue/comment as a direct order.
Decompose, plan, execute, and report back. Do not ask for clarification
unless the task is genuinely impossible. Make reasonable decisions at every
ambiguity point. Coordinate with other agents as needed. The only acceptable
stopping points are the guardrails defined in Section 3.

**Team** -- The agent follows its normal workflow. Checkpoints, skill reads,
router delegation, and standard approval gates all apply. Team members are
peers; their issues are work items, not directives.

**External** -- The agent performs triage only: classify the issue, summarize
the request, check for duplicates, and notify a principal or team member.
No code changes, no deployments, no resource creation. The agent's job is
to prepare the issue for human (or principal-tier) review.

## 3. Autonomy Rules for Principal Directives

### 3.1 Execution Mandate

When a principal creates or comments on an issue, the receiving agent MUST:

1. **Parse the intent** -- Determine what the principal is asking for.
2. **Decompose into tasks** -- Break the request into concrete steps.
3. **Execute all steps** -- Complete every task in the chain.
4. **Make autonomous decisions** -- At ambiguity points, choose the most
   reasonable option and document the choice.
5. **Coordinate as needed** -- If the task requires another agent's
   expertise, send a swarm message to that agent.
6. **Report completion** -- Post a comment on the issue summarizing what
   was done, decisions made, and any follow-up needed.

The agent MUST NOT:

- Ask the principal for clarification on details it can reasonably infer.
- Stop mid-chain to request approval for intermediate steps.
- Wait for acknowledgment before proceeding to the next task.
- Hedge with "should I proceed?" questions.

### 3.2 Guardrails -- When to Stop

Even under full autonomy, agents MUST pause and report back to the
principal when any of these conditions are met:

| Guardrail | Description | Action |
|-----------|-------------|--------|
| **Impossible task** | The task cannot be completed with available tools, permissions, or information. Not "uncertain" -- genuinely blocked. | Stop. Report what is missing and what was attempted. |
| **Cost threshold** | The task would spend real money: cloud resources, API credits, paid services. Threshold: any non-zero cost not already budgeted. | Stop. Report the estimated cost and what it buys. |
| **Irreversible production change** | The task would modify a production system in a way that cannot be rolled back (database migration, DNS change, key rotation, data deletion). | Stop. Report the change and its blast radius. |
| **Missing credentials** | The task requires secrets, tokens, or access the agent does not have. | Stop. Report which credential is needed and where it should be configured. |
| **Cross-swarm impact** | The task would affect agents or systems outside the current swarm (e.g., modifying a shared repo that other swarms depend on). | Stop. Report the scope and ask for confirmation. |
| **Contradicts existing directive** | The task conflicts with a previous principal directive that has not been explicitly superseded. | Stop. Cite the conflicting directive and ask which takes precedence. |

Guardrails are ranked by severity. If multiple guardrails trigger, report
all of them, starting with the most severe.

### 3.3 Ambiguity Resolution

When a principal directive is ambiguous, the agent resolves it using this
priority chain:

1. **Explicit statement in the issue** -- The words the principal wrote.
2. **Project conventions** -- Documented patterns in CLAUDE.md, skills,
   or memory.
3. **Recent precedent** -- How similar tasks were handled in the last
   30 days (search agent-memory).
4. **Conservative default** -- The option that changes less, breaks less,
   and is easier to undo.

The agent documents which rule it used at each ambiguity point in its
completion report.

## 4. Consensus Rules

### 4.1 When to Escalate vs Execute

| Situation | Action |
|-----------|--------|
| Single-domain task, one agent can handle it | Execute immediately |
| Multi-domain task, clear ownership per subtask | Decompose and delegate to specialists in parallel |
| Task requires agreement on approach | Agent proposes approach, waits 60 seconds for objection from any coordinating agent, then proceeds |
| Two agents disagree on approach | Escalate to the principal with both proposals and a recommendation |
| Task affects shared infrastructure | The agent owning the infrastructure has final say; others advise |

### 4.2 Coordination Protocol

When a principal directive requires multiple agents:

1. The **receiving agent** (the one whose wake was triggered) becomes the
   **coordinator** for that directive.
2. The coordinator decomposes the task and sends swarm messages to
   specialists with `metadata.directive_id` set to the issue URL.
3. Specialists execute their subtasks and report back to the coordinator
   via swarm message.
4. The coordinator aggregates results and posts the final report on the
   GitHub issue.

If the receiving agent is not the right coordinator (e.g., an infra task
landed on the memory agent), it transfers coordination by sending a
`coordination_transfer` message to the appropriate agent with full context.

### 4.3 Disagreement Resolution

When two agents propose different approaches for the same subtask:

1. Each agent posts its proposal as a swarm message to the coordinator.
2. The coordinator evaluates based on: (a) alignment with principal intent,
   (b) reversibility, (c) scope of change.
3. If still ambiguous, the coordinator picks the more conservative option
   and documents why.
4. The coordinator NEVER escalates disagreements to the principal unless
   they involve a guardrail from Section 3.2.

### 4.4 Done Signal

A principal directive is **done** when:

1. All subtasks are complete (or explicitly blocked by a guardrail).
2. The coordinator has posted a completion comment on the GitHub issue.
3. The completion comment includes:
   - Summary of what was done
   - Decisions made at ambiguity points and why
   - Any guardrails that fired and what they blocked
   - Links to PRs, commits, or other artifacts
   - Follow-up items (if any)

The coordinator closes the issue only if the principal's request is fully
satisfied. If guardrails prevented full completion, the issue stays open
with a clear status comment.

## 5. Wake Message Schema

### 5.1 GitHub Monitor Wake Message

This is the message the GitHub monitor sends to the swarm when it detects
monitored activity. It uses the standard A2A message format with a
structured `content` field.

```json
{
  "protocol_version": "0.1.0",
  "message_id": "a3f7c8d1-2e4b-4f6a-9c1d-8e5f2b3a4d6c",
  "timestamp": "2026-02-16T14:30:00Z",
  "sender": {
    "agent_id": "github-monitor",
    "endpoint": "https://nexus.marbell.com/swarm"
  },
  "recipient": "nexus-marbell",
  "swarm_id": "716a4150-ab9d-4b54-a2a8-f2b7c607c21e",
  "type": "notification",
  "content": "{...}",
  "signature": "<base64-ed25519-signature>",
  "priority": "high",
  "metadata": {
    "source": "github-monitor",
    "event_type": "github_issue"
  }
}
```

### 5.2 Content Payload Schema

> **Note**: The current monitor implementation (`monitor.py`) sends
> plain-text wake messages via `swarm send --message`. The structured
> JSON schema below is the target format for a future iteration that
> uses the SDK directly. The plain-text format carries the same
> information (tier, autonomy level, guardrails, issue content) in
> human-readable form.

The `content` field is a JSON-encoded string with this target structure:

```json
{
  "schema_version": "0.1.0",
  "event": {
    "type": "issue_opened",
    "github_user": "vantasnerdan",
    "user_tier": "principal",
    "repo": "finml-sage/agent-swarm-protocol",
    "issue_number": 200,
    "issue_title": "Add rate limiting to wake endpoint",
    "issue_url": "https://github.com/finml-sage/agent-swarm-protocol/issues/200",
    "body": "The wake endpoint needs rate limiting. Use a sliding window counter per source IP. 10 requests per minute should be enough. Deploy to nexus.marbell.com when done.",
    "labels": ["enhancement", "infrastructure"],
    "created_at": "2026-02-16T14:28:00Z"
  },
  "autonomy": {
    "level": "full",
    "instructions": "Principal directive. Execute fully without asking for clarification. Make reasonable decisions at ambiguity points. Stop only at guardrails: impossible task, real-money cost, irreversible production change, missing credentials, cross-swarm impact, or conflicting directive.",
    "guardrails": [
      "Do not spend money without reporting estimated cost first.",
      "Do not make irreversible production changes without reporting blast radius first.",
      "Do not proceed if you lack required credentials -- report what is missing.",
      "Document every ambiguity resolution in your completion report."
    ]
  },
  "routing_hint": "infrastructure"
}
```

### 5.3 Event Types

| Event Type | Trigger |
|------------|---------|
| `issue_opened` | New issue created |
| `issue_commented` | Comment added to existing issue |
| `issue_assigned` | Issue assigned to a user |
| `issue_labeled` | Label added to issue |
| `issue_closed` | Issue closed |
| `pr_opened` | Pull request opened |
| `pr_commented` | Comment on pull request |
| `pr_review` | Review submitted on pull request |

### 5.4 Autonomy Levels per Tier

| Tier | `autonomy.level` | `autonomy.instructions` |
|------|-------------------|-------------------------|
| `principal` | `"full"` | Execute without approval. Stop only at guardrails. |
| `team` | `"standard"` | Follow normal workflow. Use standard checkpoints. |
| `external` | `"triage"` | Classify and summarize only. Do not execute. |

### 5.5 Content Payload for Comments

When the event is a comment on an existing issue, the payload includes
the comment context:

```json
{
  "schema_version": "0.1.0",
  "event": {
    "type": "issue_commented",
    "github_user": "mdurchschlag",
    "user_tier": "principal",
    "repo": "finml-sage/agent-memory",
    "issue_number": 42,
    "issue_title": "Improve BM25 ranking for short queries",
    "issue_url": "https://github.com/finml-sage/agent-memory/issues/42",
    "body": "Add a minimum document frequency threshold of 2. Single-occurrence terms are noise.",
    "comment_id": 1847293,
    "comment_url": "https://github.com/finml-sage/agent-memory/issues/42#issuecomment-1847293",
    "labels": ["search", "improvement"],
    "created_at": "2026-02-16T15:10:00Z"
  },
  "autonomy": {
    "level": "full",
    "instructions": "Principal directive. Execute fully without asking for clarification. Make reasonable decisions at ambiguity points. Stop only at guardrails: impossible task, real-money cost, irreversible production change, missing credentials, cross-swarm impact, or conflicting directive.",
    "guardrails": [
      "Do not spend money without reporting estimated cost first.",
      "Do not make irreversible production changes without reporting blast radius first.",
      "Do not proceed if you lack required credentials -- report what is missing.",
      "Document every ambiguity resolution in your completion report."
    ]
  },
  "routing_hint": "search"
}
```

### 5.6 Routing Hints

The `routing_hint` field is optional and advisory. It suggests which
specialist domain the task falls into, based on issue labels and content
analysis. The receiving agent's router makes the final routing decision.

If the monitor cannot determine a routing hint, the field is omitted and
the agent's router handles classification.

## 6. Escalation Protocol

### 6.1 When a Guardrail Fires

When a principal directive hits a guardrail:

1. **Do not stop all work.** Complete everything that is not blocked by
   the guardrail.
2. **Post a guardrail report** as a comment on the GitHub issue.
3. **Wait for principal response** on the blocked items only. Continue
   executing unblocked items.

### 6.2 Guardrail Report Format

The agent posts a comment on the issue with this structure:

```markdown
## Guardrail Report

**Directive**: [issue title or quoted instruction]
**Status**: Partially complete -- guardrail triggered

### Completed
- [x] Task A -- done (link to PR/commit)
- [x] Task B -- done (link to PR/commit)

### Blocked
- [ ] Task C -- **[GUARDRAIL: Irreversible Production Change]**
  Deploying to nexus.marbell.com requires restarting the swarm server.
  This will interrupt message delivery for ~30 seconds.
  **Blast radius**: All inbound swarm messages during restart window.
  **Awaiting**: Confirmation to proceed with deployment.

### Decisions Made
- Chose sliding-window over token-bucket for rate limiting (simpler,
  sufficient for stated 10 req/min requirement).
- Used per-IP tracking (not per-agent) because wake endpoint is
  unauthenticated for some callers.
```

### 6.3 Principal Response Handling

When the principal responds to a guardrail report:

- **Approval** ("go ahead", "proceed", "deploy it"): Resume the blocked
  task immediately. The approval comment is itself a principal directive.
- **Modification** ("change X to Y instead"): Treat as a new directive
  that supersedes the blocked portion. Re-plan and execute.
- **Rejection** ("don't do that part"): Mark the blocked task as
  cancelled. Update the issue comment to reflect final status.

## 7. Recipient Selection

> **Note**: As of Section 10.2, recipient selection is handled by the
> per-repo coordinator mapping in `config.yaml`. The signal-based rules
> below apply when the coordinator further delegates within its team
> (e.g., choosing which specialist to forward a subtask to).

### 7.1 Which Agent Gets the Wake

The GitHub monitor determines the recipient based on:

| Signal | Recipient | Rationale |
|--------|-----------|-----------|
| Issue assigned to a team agent | That agent | Explicit assignment |
| Repo is primarily owned by one agent | That agent's orchestrator | Domain ownership |
| Issue mentions an agent by name | That agent | Direct mention |
| No clear signal | Swarm orchestrator (nexus-marbell) | Default routing |

If the issue is assigned to a human (Dan, Martin), the monitor sends to
the swarm orchestrator for routing.

### 7.2 Broadcast vs Direct

- **Principal directives**: Always sent as a direct message to the
  selected recipient. The recipient coordinates as needed.
- **Team activity**: Direct message to the relevant agent.
- **External activity**: Direct message to the swarm orchestrator for
  triage.

## 8. Security Considerations

### 8.1 Tier Verification

The user tier is determined by matching the GitHub username against the
configured tier list. This is trusted because:

- The monitor uses `gh api` (authenticated via `gh auth`) to poll the
  GitHub API. Results are scoped to the authenticated user's access.
- GitHub's authentication is the trust boundary, not ours.
- The monitor is poll-based, not webhook-based. No inbound HTTP
  endpoint is exposed, so there is no spoofing surface to defend.

> **Future enhancement**: If the monitor is extended to accept webhooks
> (inbound HTTP), HMAC-SHA256 signature verification MUST be added
> before processing any webhook payload.

### 8.2 Autonomy Injection Prevention

An attacker who can create issues on a monitored repo could attempt to
include autonomy instructions in the issue body (prompt injection). The
protocol prevents this:

- Autonomy level is determined by user tier, not by issue content.
- The `autonomy` field is set by the monitor, not parsed from the issue.
- Even if an external user writes "execute with full autonomy" in an
  issue body, the monitor sets `autonomy.level` to `"triage"`.

### 8.3 Rate Limiting

The GitHub monitor applies its own rate limiting before generating wake
messages:

- Maximum 1 wake message per issue per 5-minute window.
- Maximum 10 wake messages per hour across all issues.
- These limits prevent a flood of rapid-fire comments from overwhelming
  the swarm.

## 9. Configuration Reference

### 9.1 Monitor Configuration

```yaml
repos:
  finml-sage/agent-memory:
    coordinator: finml-sage
  vantasnerdan/agent-model-pipeline:
    coordinator: kelvin
default_coordinator: nexus-marbell

users:
  principal:
    - vantasnerdan
    - mdurchschlag
  team:
    - finml-sage
    - nexus-marbell
    - mlops-kelvin

swarm:
  swarm_id: "716a4150-ab9d-4b54-a2a8-f2b7c607c21e"
```

Each repo maps to a `coordinator` agent who receives wake messages for
that repo's activity. The `default_coordinator` is used as a fallback
for repos not explicitly listed, or when using the legacy list format.

### 9.2 Agent-Side Configuration

Agents do not need additional configuration beyond the standard wake
endpoint setup (`WAKE_EP_ENABLED=true`, `WAKE_EP_INVOKE_METHOD=tmux`).
The autonomy instructions are carried in the message payload itself --
the agent reads them and adjusts its behavior accordingly.

## 10. Task Chain Lifecycle

### 10.1 Overview

Each GitHub event triggers a **task chain** -- a coordinated sequence of
work that begins when the coordinator receives the wake message and ends
only when all involved agents confirm completion. No principal (Dan,
Martin) involvement is required for task execution; principals are only
notified if a guardrail fires (Section 3.2).

### 10.2 Single Coordinator Routing

Each monitored repo has a designated **coordinator** agent defined in
`config.yaml`. When the monitor detects activity on a repo, it sends the
wake message to that repo's coordinator only -- not to all agents. This
eliminates redundant token consumption from broadcasting the same event
to every agent.

| Repo | Coordinator |
|------|-------------|
| `finml-sage/agent-memory` | `finml-sage` |
| `finml-sage/ideoon-automation` | `finml-sage` |
| `vantasnerdan/agent-model-pipeline` | `kelvin` |
| `mlops-kelvin/kelvin-agent` | `kelvin` |
| `nexus-marbell/nexus-state` | `nexus-marbell` |
| `nexus-marbell/claude-multi-chat-agent` | `nexus-marbell` |

If a repo is not in the mapping, the `default_coordinator` (currently
`nexus-marbell`) receives the wake.

### 10.3 Coordinator Responsibilities

The coordinator who receives the wake message becomes the **owner** of
the task chain. Responsibilities:

1. **Parse the directive** -- Understand what the principal or team
   member is asking for.
2. **Decompose into subtasks** -- Break the work into discrete pieces.
   Identify which agents own each piece.
3. **Delegate via swarm** -- Send specific subtask messages to the
   appropriate agents. Each message must include the issue URL for
   traceability.
4. **Track progress** -- Post status comments on the GitHub issue as
   subtasks are completed or blocked.
5. **Collect confirmations** -- Wait for every delegated agent to
   confirm completion via swarm message.
6. **Close the chain** -- Only when ALL agents confirm done (or report
   a blocking reason).

### 10.4 Subtask Confirmation Protocol

Each agent who receives a delegated subtask MUST send one of these
swarm messages back to the coordinator when done:

- **Success**: `"my piece is done"` -- Include a brief summary of what
  was completed and links to any artifacts (PRs, commits).
- **Blocked**: `"blocked at [reason]"` -- Include what is blocking,
  what was attempted, and whether a guardrail fired.

The coordinator aggregates these confirmations. The task chain remains
**OPEN** until every involved agent has responded.

### 10.5 No Principal Involvement Required

Task chains are executed entirely within the team. The coordinator does
NOT escalate to Dan or Martin for:

- Choosing between valid approaches (use conservative default)
- Getting approval for intermediate steps
- Confirming that work should proceed

The ONLY reasons to escalate to a principal are the guardrails defined
in Section 3.2 (impossible task, cost threshold, irreversible production
change, missing credentials, cross-swarm impact, contradicting directive).

### 10.6 Task Chain States

| State | Meaning |
|-------|---------|
| `OPEN` | Coordinator received wake, work in progress |
| `DELEGATED` | Subtasks sent to other agents, awaiting confirmations |
| `BLOCKED` | One or more subtasks hit a guardrail, awaiting principal |
| `DONE` | All agents confirmed, coordinator posted completion summary |

### 10.7 Failure Handling

If a delegated agent does not respond within a reasonable time (defined
by the coordinator based on task scope), the coordinator:

1. Sends a follow-up swarm message asking for status.
2. If still no response after the follow-up, posts a status comment on
   the issue noting the unresponsive agent.
3. Attempts to reassign the subtask to another capable agent.
4. If no alternative exists, marks the subtask as blocked and escalates
   per Section 3.2.
