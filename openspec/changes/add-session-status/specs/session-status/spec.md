## ADDED Requirements

### Requirement: Hooks forward session events to the daemon without disturbing Claude Code
The system SHALL provide a Claude Code hooks configuration that uses the built-in `http` hook type to post each event to `http://127.0.0.1:<port>/hook/<host>`, with a shared-secret header, an explicit timeout of at most 2 seconds, and never `onFailure: "block"`.

#### Scenario: Daemon not running
- **WHEN** a hook fires while no daemon is listening (or the SSH tunnel is down)
- **THEN** the failure is non-blocking, Claude Code is not held up beyond the timeout, and the session continues normally

#### Scenario: Same hook on every platform
- **WHEN** the hooks are installed on native Windows, WSL (mirrored networking), Linux, macOS, or an SSH remote with a reverse forward
- **THEN** the only difference between installations is the host tag

#### Scenario: Interrupted turn
- **WHEN** the user interrupts a turn with Esc (no `Stop` event fires)
- **THEN** the session shows "working" until its next event or the 30-minute stale timeout; this is documented as a known limitation

### Requirement: Receiver accepts only authentic hook posts
The daemon SHALL run its receiver on `127.0.0.1` only, only when `sessions = on`, and SHALL reject requests that lack `Content-Type: application/json`, carry an `Origin` header, or lack the configured token. It SHALL reply to accepted requests with `204` and an empty body.

#### Scenario: Web page tries to post
- **WHEN** a browser page sends a request to the receiver port
- **THEN** the request is rejected and the session table is unchanged

#### Scenario: Missing or wrong token
- **WHEN** a request arrives without the configured `X-Clawdmeter-Token` value
- **THEN** it is rejected and the session table is unchanged

#### Scenario: Reply never acts as a hook decision
- **WHEN** a `PermissionRequest` event is accepted
- **THEN** the reply is `204` with no body, so Claude Code's permission flow proceeds exactly as if no hook existed

#### Scenario: Feature off or port unavailable
- **WHEN** `sessions` is off, or the port cannot be bound
- **THEN** no listener is opened (or a single warning is logged), and usage display behaves exactly as before

### Requirement: Daemon maintains a persistent session table
The daemon SHALL map events to states per the design's mapping table, ignore unknown notification types, expire sessions by age, keep no hook fields beyond session id, host tag, project folder name, event name and notification type, and persist the table across daemon restarts and BLE reconnects.

#### Scenario: Permission needed
- **WHEN** a session emits `PermissionRequest`, or `Notification` with `notification_type` `permission_prompt`
- **THEN** that session's state becomes "needs you" and the device is updated within ~1 second

#### Scenario: Permission approved
- **WHEN** a session in "needs you" emits `PostToolUse`, `PostToolUseFailure` or `PreToolUse`
- **THEN** its state returns to "working"

#### Scenario: Informational notification
- **WHEN** a session emits `Notification` with a type such as `auth_success`, `agent_completed`, or a type the daemon doesn't recognize
- **THEN** the session's state is unchanged

#### Scenario: Session ends
- **WHEN** a session emits `SessionEnd`
- **THEN** it is removed from the table and from the device

#### Scenario: Daemon restarts while a session is blocked
- **WHEN** the daemon restarts while a session is in "needs you"
- **THEN** after restart the session is still shown as "needs you" (subject to the age expiry rules) without waiting for its next event

#### Scenario: Prompt text never retained
- **WHEN** an event carrying prompt text, tool input or tool output is received
- **THEN** those fields are discarded on receipt and never logged, persisted, or sent to the device

### Requirement: Sessions travel as a separate `"ss"` write that never touches usage freshness
The daemon SHALL send the session list as its own BLE write containing only `"ss"`: when the visible list changes (debounced), on a 60-second heartbeat independent of the usage poll, and right after each BLE connect. The firmware SHALL apply such a write without calling the usage update path, so usage data and its freshness stamp are untouched.

#### Scenario: Session change between usage polls
- **WHEN** a session changes state between usage polls
- **THEN** the device receives a write with only `ss`, the session list updates, and usage numbers and their stale/fresh state are unchanged

#### Scenario: Usage goes stale while sessions keep updating
- **WHEN** the usage API stops returning data but `ss` heartbeats keep arriving
- **THEN** the device still moves to the idle (stale) view on its normal timeout, with the session list visible

#### Scenario: Tool-call churn
- **WHEN** a working session fires repeated `PreToolUse`/`PostToolUse` events
- **THEN** no additional BLE write is sent, because the visible list did not change

#### Scenario: Back-to-back writes on the P4
- **WHEN** a usage write, a `qd` write and an `ss` write arrive in quick succession on the P4
- **THEN** all three are queued and parsed; none overwrites another

#### Scenario: Firmware without this change
- **WHEN** older firmware receives an `ss` write
- **THEN** it rejects the write harmlessly (nack) and its display is unaffected

#### Scenario: Daemon disappears
- **WHEN** no `ss` write has arrived for 3 minutes
- **THEN** the firmware hides the session list

### Requirement: On-device session list with attention cue
On boards where `board_caps().has_session_list` is true, the firmware SHALL render the session list (state indicator, `host/project`, state word) outside the stale-hidden usage group, hide it in the pairing view, and SHALL show an attention cue when any session newly enters "needs you", cleared by a tap on the list or when no session remains in "needs you".

#### Scenario: New blocked session
- **WHEN** a session transitions into "needs you"
- **THEN** the list shows it first with an amber indicator and the attention cue starts

#### Scenario: Acknowledge
- **WHEN** the user taps the session list while the cue is active
- **THEN** the cue stops and does not restart until another session newly enters "needs you"

#### Scenario: Blocked session resolved elsewhere
- **WHEN** the cue is active and every "needs you" session leaves that state
- **THEN** the cue stops

#### Scenario: Usage data stale
- **WHEN** usage data goes stale and the idle view shows
- **THEN** the session list remains visible and the sleeping creature is hidden while the list is non-empty

#### Scenario: Clock stays visible
- **WHEN** the session list replaces the center rotator on the P4
- **THEN** the title clock is shown

#### Scenario: Boards without the flag
- **WHEN** firmware runs on a board with `has_session_list` false
- **THEN** no session UI is created and the screen is unchanged from before this change
