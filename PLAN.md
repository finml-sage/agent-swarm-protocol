# Development Plan

## Phases Overview

```
Phase 1: Protocol Design ──────────────────────────┐
                                                   │
         ┌─────────────────────────────────────────┼─────────────────────────────────┐
         │                                         │                                 │
         ▼                                         ▼                                 ▼
Phase 2: Server                    Phase 3: Client                    Phase 4: State Management
(Angie + Handler)                  (Python Library)                   (Membership + Queue)
         │                                         │                                 │
         └─────────────────────────────────────────┼─────────────────────────────────┘
                                                   │
                                                   ▼
                                    Phase 5: Claude Code Integration
                                    (Swarm Subagent + Wake Triggers)
                                                   │
                                                   ▼
                                    Phase 6: CLI
                                    (User Interface)
```

## Phase 1: Protocol Design
**Status**: Ready
**Dependencies**: None
**Parallel**: No (foundation for everything)

### Tasks
1. [ ] Define message JSON schema with required fields
2. [ ] Define swarm operations and their payloads
3. [ ] Define invite token format and validation
4. [ ] Define membership state schema
5. [ ] Define endpoint specifications (REST API)
6. [ ] Write protocol specification document

### Deliverables
- `docs/PROTOCOL.md`
- `docs/MESSAGE-SCHEMA.md`
- `schemas/message.json`
- `schemas/swarm-state.json`

---

## Phase 2: Server
**Status**: Blocked (waiting on Phase 1)
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 3, 4)

### Tasks
1. [ ] Angie HTTP/3 configuration template
2. [ ] Angie ACME (built-in) configuration
3. [ ] Python message receiver (FastAPI or Flask)
4. [ ] Message validation against schema
5. [ ] Request authentication (signature verification)
6. [ ] Rate limiting and abuse prevention
7. [ ] Health check endpoint

### Deliverables
- `src/server/angie.conf.template`
- `src/server/handler.py`
- `src/server/auth.py`
- `src/server/validation.py`

---

## Phase 3: Client
**Status**: Blocked (waiting on Phase 1)
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 2, 4)

### Tasks
1. [ ] Python client library structure
2. [ ] Send message function
3. [ ] Swarm operations (create, join, leave, kick)
4. [ ] Invite token generation and parsing
5. [ ] Member discovery and endpoint resolution
6. [ ] Retry logic and error handling
7. [ ] Message signing with agent's private key

### Deliverables
- `src/client/__init__.py`
- `src/client/swarm.py`
- `src/client/message.py`
- `src/client/crypto.py`

---

## Phase 4: State Management
**Status**: Blocked (waiting on Phase 1)
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 2, 3)

### Tasks
1. [ ] SQLite schema for message queue
2. [ ] Swarm membership storage (JSON or SQLite)
3. [ ] Mute lists (swarm-level, agent-level)
4. [ ] Message history with retention policy
5. [ ] Unread message tracking
6. [ ] State export/import for portability

### Deliverables
- `src/state/database.py`
- `src/state/membership.py`
- `src/state/mutes.py`
- `src/state/schema.sql`

---

## Phase 5: Claude Code Integration
**Status**: Blocked (waiting on Phases 2, 3, 4)
**Dependencies**: Phases 2, 3, 4
**Parallel**: No

### Tasks
1. [ ] Swarm subagent definition (SKILL.md format)
2. [ ] Wake trigger integration (POST to /api/wake)
3. [ ] Context loader (recent messages, membership state)
4. [ ] Response handler (send replies via client)
5. [ ] Notification preferences (what triggers wake)
6. [ ] Claude Code SDK session management

### Deliverables
- `src/claude/swarm-subagent/SKILL.md`
- `src/claude/wake_trigger.py`
- `src/claude/context_loader.py`
- `docs/CLAUDE-INTEGRATION.md`

---

## Phase 6: CLI
**Status**: Blocked (waiting on Phases 3, 4)
**Dependencies**: Phases 3, 4
**Parallel**: Partially (can start after Phase 3)

### Tasks
1. [ ] CLI framework setup (Click or Typer)
2. [ ] `swarm init` - Initialize agent for swarm participation
3. [ ] `swarm create` - Create new swarm
4. [ ] `swarm invite` - Generate invite token
5. [ ] `swarm join` - Join swarm with token
6. [ ] `swarm leave` - Leave a swarm
7. [ ] `swarm list` - List swarms and members
8. [ ] `swarm send` - Send message
9. [ ] `swarm mute/unmute` - Manage mutes
10. [ ] `swarm status` - Show connection status

### Deliverables
- `cli/swarm.py`
- `docs/CLI.md`

---

## Task Complexity Guide

| Complexity | Description | Typical Scope |
|------------|-------------|---------------|
| Simple | Single function, clear spec | 1-2 hours |
| Medium | Multiple functions, some decisions | 2-4 hours |
| Complex | System design, integration | 4+ hours |

---

## Workflow for Agent Contributors

### Claiming a Task
1. Find an issue with `status:ready` label
2. Comment: "Claiming this task"
3. Maintainer adds `status:in-progress` and assigns you

### Completing a Task
1. Create branch: `phase-N/task-description`
2. Implement with tests
3. Submit PR referencing the issue
4. Address review feedback
5. Issue closed on merge

### Blocked?
1. Comment on the issue explaining the blocker
2. Maintainer adds `status:blocked` label
3. Create a new issue for the blocker if needed

### Parallel Work
Tasks marked `parallel:yes` can be worked on simultaneously by different agents. Coordinate in the issue comments if there's overlap.

---

## Milestones

### M1: Protocol Complete
- All Phase 1 tasks done
- Protocol spec reviewed and finalized

### M2: Core Infrastructure
- Phases 2, 3, 4 complete
- Agents can send/receive messages

### M3: Full Integration
- Phase 5 complete
- Claude Code can process swarm messages

### M4: Production Ready
- Phase 6 complete
- Documentation complete
- Test coverage > 80%
