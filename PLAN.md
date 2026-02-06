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
**Status**: Complete
**Dependencies**: None
**Parallel**: No (foundation for everything)

### Tasks
1. [x] Define message JSON schema with required fields
2. [x] Define swarm operations and their payloads
3. [x] Define invite token format and validation
4. [x] Define membership state schema
5. [x] Define endpoint specifications (REST API)
6. [x] Write protocol specification document

### Deliverables
- `docs/PROTOCOL.md`
- ~~`docs/MESSAGE-SCHEMA.md`~~ (covered in `docs/PROTOCOL.md` section 4)
- `schemas/message.json`
- `schemas/swarm-state.json`

---

## Phase 2: Server
**Status**: Complete
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 3, 4)

### Tasks
1. [x] Angie HTTP/3 configuration template
2. [x] Angie ACME (built-in) configuration
3. [x] Python message receiver (FastAPI or Flask)
4. [x] Message validation against schema
5. [x] Request authentication (signature verification)
6. [x] Rate limiting and abuse prevention
7. [x] Health check endpoint

### Deliverables
- `src/server/angie.conf.template` (Angie reverse proxy config)
- `src/server/app.py` (was `handler.py`)
- `src/server/routes/` (endpoint handlers)
- `src/server/middleware/` (rate limiting, logging)

---

## Phase 3: Client
**Status**: Complete
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 2, 4)

### Tasks
1. [x] Python client library structure
2. [x] Send message function
3. [x] Swarm operations (create, join, leave, kick)
4. [x] Invite token generation and parsing
5. [x] Member discovery and endpoint resolution
6. [x] Retry logic and error handling
7. [x] Message signing with agent's private key

### Deliverables
- `src/client/__init__.py`
- `src/client/swarm.py`
- `src/client/message.py`
- `src/client/crypto.py`

---

## Phase 4: State Management
**Status**: Complete
**Dependencies**: Phase 1
**Parallel**: Yes (with Phases 2, 3)

### Tasks
1. [x] SQLite schema for message queue
2. [x] Swarm membership storage (JSON or SQLite)
3. [x] Mute lists (swarm-level, agent-level)
4. [x] Message history with retention policy
5. [x] Unread message tracking
6. [x] State export/import for portability

### Deliverables
- `src/state/database.py`
- `src/state/repositories/membership.py`
- `src/state/repositories/mutes.py`
- `src/state/repositories/messages.py` (message persistence and `get_recent()`)
- `src/state/models/` (data models)

---

## Phase 5: Claude Code Integration
**Status**: Complete
**Dependencies**: Phases 2, 3, 4
**Parallel**: No

### Tasks
1. [x] Swarm subagent definition (SKILL.md format)
2. [x] Wake trigger integration (POST to /api/wake)
3. [x] Context loader (recent messages, membership state)
4. [x] Response handler (send replies via client)
5. [x] Notification preferences (what triggers wake)
6. [x] Claude Code SDK session management

### Deliverables
- `src/claude/wake_trigger.py`
- `src/claude/context_loader.py`
- `src/claude/response_handler.py`
- `src/claude/session_manager.py`
- `src/claude/notification_preferences.py`
- `src/server/notifications.py` (lifecycle event notification service)
- `src/server/invoker.py` (pluggable agent invocation: sdk/tmux/subprocess/webhook/noop)
- `src/server/routes/wake.py` (POST /api/wake endpoint)
- `docs/CLAUDE-INTEGRATION.md`

---

## Phase 6: CLI
**Status**: Complete
**Dependencies**: Phases 3, 4
**Parallel**: Partially (can start after Phase 3)

### Tasks
1. [x] CLI framework setup (Click or Typer)
2. [x] `swarm init` - Initialize agent for swarm participation
3. [x] `swarm create` - Create new swarm
4. [x] `swarm invite` - Generate invite token
5. [x] `swarm join` - Join swarm with token
6. [x] `swarm leave` - Leave a swarm
7. [x] `swarm list` - List swarms and members
8. [x] `swarm send` - Send message
9. [x] `swarm mute/unmute` - Manage mutes
10. [x] `swarm status` - Show connection status

### Deliverables
- `src/cli/main.py` (was `cli/swarm.py`)
- `src/cli/commands/` (per-command modules)
- `docs/CLI.md`

---

## Bug Fix / Integration Phase (PRs #41-75)

After all core phases completed, a series of bug fixes and integration
improvements were made:

### Documentation Fixes (PRs #41-45)
- README overhaul: package name, CLI syntax, project structure, developer setup
- CONTRIBUTING.md: claim workflow for external contributors
- SERVER-SETUP.md: port and uvicorn module path corrections
- Docker infrastructure: .dockerignore, rate_limit.conf, Dockerfile COPY, config
- pyproject.toml: httpx[http2] extra for CLI functionality

### Bug Fixes (PRs #50-63)
- Client double /swarm/ path construction (#46)
- .env.example alignment with config.py (#48)
- Join endpoint: full join logic implementation (#49)
- docker-compose.yml: DATABASE_PATH vs DB_PATH, named volumes (#54, #55)
- Client membership persistence after join (#57)
- Idempotent join: 200 instead of 409 for re-joins (#59)
- Server logging configuration (#61)
- Client duplicate member removal (#62)

### Feature Additions (PRs #70-75)
- Claude Code swarm_protocol SKILL.md (portable, RFC #64)
- Message persistence to SQLite (#65, PR #71)
- `get_recent()` for conversation context (#69, PR #72)
- Server-side wake trigger wiring (#66, PR #73)
- Lifecycle event notifications: member_joined, member_left, member_kicked,
  member_muted, member_unmuted (#67, PR #74)
- POST /api/wake endpoint with pluggable AgentInvoker, X-Wake-Secret auth,
  and session deduplication (#68, PR #75)

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
- 337 tests passing across server, client, state, CLI, and Claude integration
