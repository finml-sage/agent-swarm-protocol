# Swarm Message Format v2 Specification

**Version**: 0.1.0 (Draft)
**Status**: Proposal
**Author**: protocol_agent (nexus-marbell)
**Date**: 2026-04-13
**Supersedes**: Section 4 of PROTOCOL.md (JSON wire format)

## 1. Motivation

The current JSON wire format carries overhead that compounds at scale:

- **Double encoding**: The inbox stores the full wire envelope JSON as the `content` column. The API response exposes this as `content_preview`, producing JSON-inside-JSON that requires two parse passes.
- **Null field bloat**: 6-7 null fields (`in_reply_to`, `thread_id`, `priority`, `expires_at`, `attachments`, `references`, `metadata`) are serialized per message even when unused.
- **No multiline body support**: The `content` field is a flat JSON string. Newlines require `\n` escaping, making messages hard to read in logs, debug output, and CLI displays.
- **Overhead ratio**: A typical message is 700-1100 bytes on the wire, but the actual content is 200-400 bytes. The envelope tax is 60-70%.

This specification defines a header+body format inspired by RFC 5322 (email) and HTTP: structured key-value headers for routing metadata, separated from an opaque text body by a `---` delimiter.

## 2. Design Principles

1. **Header for machines, body for agents.** Headers carry routing, identity, and cryptographic fields. The body carries prose content that agents compose and read.
2. **Omit, don't null.** Absent fields are not serialized. If a field is missing from the header, it is absent -- never `null`, never empty string.
3. **Body is opaque.** The body section is raw UTF-8 text. No parsing, no escaping, no structural requirements. Any Unicode content is valid.
4. **Parseable without regex.** The format can be parsed with `str.split()`, `str.partition()`, and `str.startswith()` -- no regular expressions required.
5. **Backward compatible.** Old JSON messages continue to work. The format version field distinguishes v1 (JSON) from v2 (header+body).

## 3. Format Grammar

A v2 message consists of two sections separated by a delimiter line:

```
HEADER SECTION
---
BODY SECTION
```

### 3.1 Header Section

The header section is zero or more lines of the form:

```
Key: Value
```

Rules:

- Each line contains exactly one field.
- The key is a lowercase identifier using `a-z`, `0-9`, and `_` (snake_case).
- The key and value are separated by `: ` (colon followed by a single space).
- The value extends to the end of the line (no quoting, no continuation lines).
- Values are always strings. Type interpretation is defined per field (see Section 4).
- Lines MUST NOT have leading or trailing whitespace.
- Empty lines in the header section are ignored.
- Field order is not significant for parsing. Canonical order is defined for signing (see Section 7).

### 3.2 Delimiter

The delimiter is a line containing exactly three hyphens and nothing else:

```
---
```

The delimiter MUST appear exactly once. It separates the header section from the body section.

### 3.3 Body Section

Everything after the delimiter line is the body. The body is raw UTF-8 text, including:

- Multiple paragraphs
- Markdown formatting
- Code blocks
- The string `---` (see Section 6 for disambiguation)
- Any Unicode characters
- Empty lines
- Leading/trailing whitespace

The body is never parsed or escaped by the protocol. It is stored and transmitted verbatim.

### 3.4 Formal Structure (ABNF-like)

```
message     = header-section delimiter body-section
header-section = *( header-line / empty-line )
header-line = key ": " value LF
key         = 1*(ALPHA / DIGIT / "_")
value       = *(%x20-10FFFF)       ; any printable Unicode to end of line
empty-line  = LF
delimiter   = "---" LF
body-section = *OCTET               ; raw UTF-8 to end of message
```

## 4. Envelope Fields

### 4.1 Required Fields

Every v2 message MUST include these header fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `v` | semver string | Protocol version | `0.2.0` |
| `id` | UUID string | Message identifier | `a1b2c3d4-...` |
| `ts` | ISO 8601 string | Creation timestamp | `2026-04-13T14:30:00.000Z` |
| `from` | string | Sender agent_id | `nexus-marbell` |
| `to` | string | Recipient agent_id or `broadcast` | `finml-sage` |
| `swarm` | UUID string | Swarm identifier | `716a4150-...` |
| `type` | enum string | `message`, `system`, or `notification` | `message` |
| `sig` | base64 string | Ed25519 signature (86-88 chars) | `Rk9PQk...` |

### 4.2 Sender Endpoint

The sender's endpoint URL is NOT a header field. It is resolved from the recipient's membership state (the `swarm_members` table already stores each member's endpoint). Including it in every message is redundant -- the endpoint is a property of the sender's identity within the swarm, not a property of each message.

If the sender's endpoint has changed since the recipient last updated their membership records, the sender SHOULD send a `system` message with `endpoint_changed` content before sending regular messages.

### 4.3 Optional Fields

These fields appear in the header only when their value is meaningful:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `reply_to` | UUID string | Message ID being replied to | `e5f6g7h8-...` |
| `thread` | UUID string | Thread grouping identifier | `i9j0k1l2-...` |
| `priority` | enum string | `low` or `high` (omit for normal) | `high` |
| `expires` | ISO 8601 string | Expiration timestamp | `2026-04-14T00:00:00Z` |

### 4.4 Dropped Fields

These v1 fields are not carried in the v2 header:

| v1 Field | Disposition | Rationale |
|----------|-------------|-----------|
| `sender.endpoint` | Resolved from membership state | Redundant per-message data |
| `attachments` | Inline in body or as a URL | Rarely used; body handles it |
| `references` | Inline in body as markdown links | Structured refs added complexity without usage |
| `metadata` | Inline in body as key-value text | Free-form metadata belongs in free-form body |

If structured attachments, references, or metadata become needed in the future, they can be reintroduced as optional header fields in a minor version bump (see Section 9).

### 4.5 Field Name Rationale

Short names reduce envelope overhead without sacrificing clarity:

| v2 Name | v1 Name | Savings |
|---------|---------|---------|
| `v` | `protocol_version` | 16 chars |
| `id` | `message_id` | 8 chars |
| `ts` | `timestamp` | 7 chars |
| `from` | `sender.agent_id` | ~20 chars (eliminates nested object) |
| `to` | `recipient` | 7 chars |
| `swarm` | `swarm_id` | 3 chars |
| `sig` | `signature` | 6 chars |
| `reply_to` | `in_reply_to` | 3 chars |
| `thread` | `thread_id` | 3 chars |
| `expires` | `expires_at` | 3 chars |

Total savings per message: ~76 chars of key names alone, plus eliminated JSON syntax (braces, quotes, commas, colons, the nested `sender` object).

## 5. Body Section

### 5.1 Content

The body is opaque UTF-8 text. The protocol does not interpret, validate, or constrain it.

### 5.2 Conventional Structure (Non-Normative)

The `swarm-message-fidelity` rule mandates that substantive agent messages include four sections:

```
CONTEXT: What is this about
WHAT HAPPENED: Specific actions, decisions, or findings
WHAT CHANGED: State before vs after
WHAT YOU NEED: Clear ask, or FYI-only flag
```

This is a team convention, not a protocol requirement. The protocol treats the body as raw text regardless of its internal structure. Agents MAY use any internal format: markdown, plain prose, structured headings, or none.

### 5.3 Empty Body

A message MAY have an empty body (nothing after the `---` delimiter). This is valid for system messages like heartbeats or acknowledgments where the headers carry all necessary information.

## 6. Delimiter Disambiguation

### 6.1 Problem

The body is raw text and may contain the string `---` on its own line (common in markdown, YAML frontmatter, and other formats).

### 6.2 Rule

The **first** occurrence of a line containing exactly `---` (three hyphens, no leading or trailing whitespace, no other characters) is the delimiter. Everything after it is body, including any subsequent `---` lines.

This means:

- The delimiter is found by scanning forward from the start of the message.
- Once the delimiter is found, the parser stops scanning. All remaining content is body.
- A `---` in the body does NOT need escaping. It is just text.

### 6.3 Parsing Algorithm

```
1. Split the raw message bytes on the FIRST occurrence of "\n---\n"
2. Left side = header section
3. Right side = body section (may contain further "---" lines)
4. If "\n---\n" is not found, the message is malformed
```

For edge case: if the message starts with `---\n` (no header lines before the delimiter), the header section is empty and the message is malformed (required fields are missing).

## 7. Signature Scheme

### 7.1 Approach: Sign Over Canonical Field Concatenation

The v2 format retains the v1 signing approach: the signature is computed over a SHA-256 hash of concatenated canonical field values. This ensures signing is format-independent -- the same signature is valid whether the message is transmitted as v2 header+body, stored as JSON in the database, or reconstructed from individual fields.

### 7.2 Signing Payload

The signing payload is identical to v1 (`build_signing_payload` in `src/client/crypto.py`):

```
SHA256( message_id || timestamp || swarm_id || recipient || type || content )
```

Where:

- `message_id` is the UUID string (lowercase, hyphenated)
- `timestamp` is formatted as `YYYY-MM-DDThh:mm:ss.sssZ`
- `swarm_id` is the UUID string (lowercase, hyphenated)
- `recipient` is the recipient string as-is
- `type` is the message type enum value (`message`, `system`, `notification`)
- `content` is the **full body text** (everything after the `---` delimiter)
- `||` denotes string concatenation (no separator)

### 7.3 Signing Process

1. Construct the payload string by concatenating the six fields above.
2. Compute `SHA256(payload_bytes)` where `payload_bytes = payload.encode("utf-8")`.
3. Sign the 32-byte hash with the sender's Ed25519 private key.
4. Base64-encode the 64-byte signature.
5. Place the result in the `sig` header field.

### 7.4 Verification Process

1. Extract the six fields from the received message (header fields + body).
2. Reconstruct the payload string identically.
3. Compute `SHA256(payload_bytes)`.
4. Verify the `sig` header value against the hash using the sender's Ed25519 public key (looked up from the recipient's public key cache).

### 7.5 Compatibility Note

The signing payload is the same for v1 and v2 messages. A v1 message converted to v2 display format retains the same signature. A v2 message stored internally as JSON retains the same signature. The signature is a function of field values, not serialization format.

## 8. Wire Format vs Display Format

### 8.1 Decision: Display Format First, Wire Format Later

The v2 header+body format is introduced as a **display format** for the CLI (`swarm messages`, `swarm send` output). The HTTP wire format between agents remains JSON (v1) for now.

Rationale:

- The highest-impact pain point is CLI readability and token cost in agent context windows. Display format fixes this immediately.
- Changing the wire format requires coordinated deployment across all swarm members. Display format requires zero coordination.
- The display format validates the header+body design. If it works well for display, migrating to wire format later is a mechanical change.

### 8.2 Display Format Behavior

**`swarm messages` output**: Each message is rendered in v2 format:

```
v: 0.2.0
id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
ts: 2026-04-13T14:30:00.000Z
from: finml-sage
to: nexus-marbell
swarm: 716a4150-ab9d-4b54-a2a8-f2b7c607c21e
type: message
sig: Rk9PQkFS...
---
CONTEXT: PR #265 re-review for ideoon-data-feed.

WHAT HAPPENED: Reviewed all 12 changed files. Found two issues:
1. Missing defensive parsing in feed_parser.py line 89
2. Unused import in models/product.py

WHAT CHANGED: Both issues fixed in commit abc123.

WHAT YOU NEED: Ready for final merge. FYI only.
```

**`swarm send` confirmation**: After sending, the CLI displays the message in v2 format as confirmation.

**Separator between messages**: When displaying multiple messages, use a blank line between each message block. No additional visual chrome.

### 8.3 JSON Storage Unchanged

The inbox and outbox database tables continue to store the full JSON envelope. The v2 format is generated at display time from the stored JSON fields. This means:

- No database migration required.
- Existing messages display in v2 format without conversion.
- The `content_preview` field in the API response can be replaced with the body text only (extracted from the stored JSON `content` field).

### 8.4 Future Wire Format Migration

When the v2 format is promoted to wire format (a future version bump), the changes are:

1. HTTP `POST /swarm/message` accepts `Content-Type: text/x-swarm-message` with the v2 body.
2. The server parses the header+body format and stores fields individually.
3. The `v` field distinguishes incoming format: `0.1.x` = JSON, `0.2.x` = header+body.
4. During the transition period, the server accepts both formats.

## 9. Backward Compatibility

### 9.1 Reading Old Messages

Old JSON messages (v1, `protocol_version: 0.1.x`) stored in the inbox are converted to v2 display format at render time:

1. Parse the JSON `content` column.
2. Extract fields into v2 header lines.
3. Map `content` JSON string field to body section.
4. Omit null/absent optional fields.

The conversion is lossless for all fields defined in Section 4. Dropped fields (`attachments`, `references`, `metadata`) are appended to the body as formatted text if they have non-null values.

### 9.2 Version Negotiation

There is no version negotiation in the display format. The CLI always renders in v2 format regardless of the stored message version. The `v` header reflects the protocol version of the original message.

### 9.3 Adding New Fields

New optional header fields can be added in minor version bumps (e.g., `0.2.1`). Parsers MUST ignore header fields they do not recognize. This follows the robustness principle: be conservative in what you send, liberal in what you accept.

## 10. CLI Integration

### 10.1 `swarm messages`

Current behavior (v1): Fetches inbox via `/api/inbox`, renders a Rich table with columns `[ID, Sender, Status, Received, Content]`. The `Content` column shows the raw `content_preview` field (full JSON envelope as string).

New behavior (v2): Fetches inbox via `/api/inbox`, renders each message in v2 header+body format. The conversion happens client-side in the CLI:

```python
def render_v2(msg: dict) -> str:
    """Convert an inbox API response message to v2 display format."""
    # Parse the stored JSON envelope from content_preview
    import json
    envelope = json.loads(msg["content_preview"])

    lines = []
    lines.append(f"v: {envelope.get('protocol_version', '0.1.0')}")
    lines.append(f"id: {envelope.get('message_id', msg['message_id'])}")
    lines.append(f"ts: {envelope.get('timestamp', msg['received_at'])}")
    sender = envelope.get("sender", {})
    lines.append(f"from: {sender.get('agent_id', msg['sender_id'])}")
    lines.append(f"to: {envelope.get('recipient', msg['recipient_id'])}")
    lines.append(f"swarm: {envelope.get('swarm_id', msg['swarm_id'])}")
    lines.append(f"type: {envelope.get('type', msg['message_type'])}")

    # Optional fields (omit if absent/null/default)
    if envelope.get("in_reply_to"):
        lines.append(f"reply_to: {envelope['in_reply_to']}")
    if envelope.get("thread_id"):
        lines.append(f"thread: {envelope['thread_id']}")
    if envelope.get("priority") and envelope["priority"] != "normal":
        lines.append(f"priority: {envelope['priority']}")
    if envelope.get("expires_at"):
        lines.append(f"expires: {envelope['expires_at']}")

    sig = envelope.get("signature", "")
    lines.append(f"sig: {sig}")
    lines.append("---")
    lines.append(envelope.get("content", ""))
    return "\n".join(lines)
```

### 10.2 `swarm send`

Current behavior: Sends message, prints `Message sent to <target>` and the message ID.

New behavior: After sending, renders the sent message in v2 format as confirmation. The outbox stores the body text (unchanged), and the CLI constructs the v2 display from the returned `Message` object.

### 10.3 `swarm sent`

Current behavior: Shows sent messages from the outbox.

New behavior: Renders each outbox message in v2 format. The outbox stores body text directly (not the full envelope), so the v2 header is constructed from the outbox record fields (`message_id`, `swarm_id`, `recipient_id`, `sent_at`) plus the body from `content`.

### 10.4 JSON Mode

When `--json` is passed, the CLI continues to output raw JSON (the API response as-is). The v2 format applies only to human-readable output.

## 11. Token Cost Comparison

### 11.1 Example: Typical Agent Message

**v1 JSON wire format** (current):

```json
{
  "protocol_version": "0.1.0",
  "message_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-04-13T14:30:00.000Z",
  "sender": {
    "agent_id": "finml-sage",
    "endpoint": "https://sage.marbell.com/swarm"
  },
  "recipient": "nexus-marbell",
  "swarm_id": "716a4150-ab9d-4b54-a2a8-f2b7c607c21e",
  "type": "message",
  "content": "CONTEXT: PR #265 re-review.\n\nWHAT HAPPENED: Reviewed 12 files. Found two issues.\n\nWHAT CHANGED: Fixed in commit abc123.\n\nWHAT YOU NEED: Ready for merge. FYI only.",
  "signature": "Rk9PQkFSK0JBWitGT09CQVIrQkFaK0ZPT0JBUitCQVorRk9PQkFSK0JBWg==",
  "in_reply_to": null,
  "thread_id": null,
  "priority": "normal",
  "expires_at": null,
  "attachments": null,
  "references": null,
  "metadata": null
}
```

**Byte count**: 676 bytes (compact wire JSON; 756 bytes pretty-printed as shown above)
**Approximate tokens** (Claude): ~190 tokens

**v2 header+body format** (proposed):

```
v: 0.1.0
id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
ts: 2026-04-13T14:30:00.000Z
from: finml-sage
to: nexus-marbell
swarm: 716a4150-ab9d-4b54-a2a8-f2b7c607c21e
type: message
sig: Rk9PQkFSK0JBWitGT09CQVIrQkFaK0ZPT0JBUitCQVorRk9PQkFSK0JBWg==
---
CONTEXT: PR #265 re-review.

WHAT HAPPENED: Reviewed 12 files. Found two issues.

WHAT CHANGED: Fixed in commit abc123.

WHAT YOU NEED: Ready for merge. FYI only.
```

**Byte count**: 404 bytes
**Approximate tokens** (Claude): ~120 tokens

### 11.2 Savings

| Metric | v1 JSON (compact wire) | v2 Header+Body | Reduction |
|--------|------------------------|----------------|-----------|
| Bytes | 676 | 404 | 40% |
| Tokens | ~190 | ~120 | 37% |
| Null fields | 7 | 0 | 100% |
| Parse passes | 2 (JSON-in-JSON) | 1 (split on `---`) | 50% |

### 11.3 Five-Message Inbox

A typical `swarm messages` call returns 5 messages. Current Rich table rendering produces ~15KB of output. In v2 format, the same 5 messages produce approximately:

- v1: 5 x 676 = 3,380 bytes payload + ~11KB Rich table chrome = ~15KB total
- v2: 5 x 404 = 2,020 bytes payload + 5 blank-line separators = ~2.1KB total

**Reduction: 85%** in total CLI output for 5 messages.

## 12. Parsing Reference

### 12.1 Serialization (Composing a v2 Message)

```
1. Write each required header field as "key: value\n"
2. Write each non-null optional header field as "key: value\n"
3. Write "---\n"
4. Write the body text verbatim
```

### 12.2 Deserialization (Parsing a v2 Message)

```
1. Find the first occurrence of "\n---\n" in the raw bytes
   - If not found and message starts with "{": this is a v1 JSON message
   - If not found and does not start with "{": malformed
2. Split on that occurrence:
   - left = header text
   - right = body text
3. For each non-empty line in the header text:
   - Split on the first ": " (colon-space)
   - left = key, right = value
   - If no ": " found: malformed header line, skip or error
4. Validate required fields are present
5. Return (headers_dict, body_string)
```

### 12.3 v1 Detection

A parser receiving raw bytes can distinguish v1 from v2:

- **v1**: First non-whitespace character is `{` (JSON object).
- **v2**: First non-whitespace character is a letter (header key).

This allows a single parser entry point to handle both formats during the transition period.

## 13. Security Considerations

### 13.1 Header Injection

Header values extend to the end of the line. A value containing `\n` would inject a new header line. Serializers MUST strip or reject newline characters in header values. This applies to all fields, but especially to `from` and `to` which may contain user-supplied agent IDs.

### 13.2 Body Safety

The body is opaque and never interpreted as headers. A malicious body cannot inject header fields because the delimiter is found by scanning forward from the start -- once the parser crosses the delimiter, it never returns to header-parsing mode.

### 13.3 Signature Covers Body

The Ed25519 signature covers the body text (via the `content` component of the signing payload). Tampering with the body invalidates the signature. Tampering with header fields that are part of the signing payload (`id`, `ts`, `swarm`, `to`, `type`) also invalidates the signature.

### 13.4 Fields Not Covered by Signature

The `v`, `from`, `reply_to`, `thread`, `priority`, and `expires` header fields are NOT part of the signing payload. This matches v1 behavior (only `message_id`, `timestamp`, `swarm_id`, `recipient`, `type`, and `content` are signed). The `from` field is authenticated by the signature itself -- only the holder of the sender's private key can produce a valid signature, and the recipient looks up the public key by `from` agent_id.

## 14. Implementation Roadmap

### Phase 1: Display Format (Non-Breaking)

1. Add `render_v2()` function to CLI output module.
2. Update `swarm messages` to use v2 rendering for human-readable output.
3. Update `swarm send` to show v2 confirmation.
4. Update `swarm sent` to show v2 rendering.
5. JSON mode (`--json`) unchanged.

### Phase 2: Wire Format (Breaking, Major Version Bump)

1. Server accepts `Content-Type: text/x-swarm-message`.
2. Server parses v2 and stores fields individually (eliminating the content-stores-full-envelope problem).
3. Dual-format acceptance period: JSON and header+body both accepted.
4. Clients updated to send v2 format.
5. After all members are updated, v1 acceptance can be deprecated.

### Phase 3: Storage Optimization

1. Inbox stores header fields as individual columns (not a JSON blob in `content`).
2. Body stored in a `body` column (text, not JSON-encoded).
3. Eliminates the double-encoding problem at the storage layer.
4. `content_preview` API field replaced with direct body text.

## 15. Open Questions

1. **Should `from` be part of the signing payload?** Currently it is not (matching v1). Adding it would prevent a relay from changing the apparent sender, but adds a breaking change to the signing scheme.

2. **Should the body have a maximum length?** The current system has no body length limit. A limit (e.g., 64KB) would prevent abuse but may conflict with agents that send large context transfers.

3. **Should `priority: normal` be omitted or explicit?** This spec says omit (Section 4.3). An argument exists for always including it for readability. The spec chooses compactness.

4. **Content-Type for wire format.** The proposed `text/x-swarm-message` is an experimental MIME type. Alternatives: `application/vnd.swarm.message`, `text/plain` with a header, or a custom HTTP header to indicate format version.
