## ADDED Requirements

### Requirement: Hooks forward session events to the daemon without disturbing Claude Code
The system SHALL provide a Claude Code hooks configuration whose command forwards the hook's stdin JSON to the daemon receiver via `curl` with a 1-second timeout, tagged with a per-machine host label, and that exits successfully even when the daemon is unreachable.

#### Scenario: Daemon not running
- **WHEN** a hook fires while no daemon is listening (or the SSH tunnel is down)
- **THEN** the hook finishes within ~1 second, Claude Code shows no error and is not blocked, and the session continues normally

#### Scenario: Same hook on every platform
- **WHEN** the hooks are installed on native Windows, WSL (mirrored networking), Linux, macOS, or an SSH remote with a reverse forward
- **THEN** the only differences between installations are the host tag and, on native Windows, `curl.exe` instead of `curl`

### Requirement: Daemon maintains a session table from hook events
The daemon SHALL run a receiver on `127.0.0.1` (configurable port) only when `sessions = on`, map events to states (working, needs you, your turn, removed), expire sessions by age into stale and then drop them, and keep no hook fields beyond session id, host tag, project folder name, event name and notification type.

#### Scenario: Permission prompt
- **WHEN** a session emits `Notification` with `notification_type` `permission_prompt`
- **THEN** that session's state becomes "needs you" and the device is updated within ~1 second

#### Scenario: Permission approved
- **WHEN** a session in "needs you" emits `PostToolUse` or `PreToolUse`
- **THEN** its state returns to "working"

#### Scenario: Session ends
- **WHEN** a session emits `SessionEnd`
- **THEN** it is removed from the table and from the device

#### Scenario: Feature off or port unavailable
- **WHEN** `sessions` is off, or the port cannot be bound
- **THEN** no listener is opened (or a single warning is logged), and usage display behaves exactly as before

#### Scenario: Prompt text never retained
- **WHEN** a `UserPromptSubmit` event carrying prompt text is received
- **THEN** the prompt text is discarded on receipt and never logged or sent to the device

### Requirement: Sessions travel as a separate, mergeable `"ss"` write
The daemon SHALL send the session list as its own BLE write containing `"ss"` (and optionally `"sn"`) and no usage fields, on change (debounced) and once per usage poll. The firmware SHALL treat such a write as a merge that leaves usage data and its freshness stamp untouched.

#### Scenario: Session change between usage polls
- **WHEN** a session changes state between usage polls
- **THEN** the device receives a write with only `ss`, the session list updates, and usage numbers and their stale/fresh state are unchanged

#### Scenario: Older firmware
- **WHEN** a firmware build without this change receives an `ss` write
- **THEN** it ignores the field without error

#### Scenario: Daemon disappears
- **WHEN** no `ss` write has arrived for 3 minutes
- **THEN** the firmware hides the session list

### Requirement: On-device session list with attention cue
On boards where `board_caps().has_session_list` is true, the firmware SHALL render the session list (state indicator, host, project) outside the stale-hidden usage group, and SHALL show an attention cue when any session newly enters "needs you", cleared by a tap or by no session being in "needs you".

#### Scenario: New blocked session
- **WHEN** a session transitions into "needs you"
- **THEN** the list shows it first with an amber indicator and the attention cue starts

#### Scenario: Acknowledge
- **WHEN** the user taps the session list while the cue is active
- **THEN** the cue stops and does not restart until another session newly enters "needs you"

#### Scenario: Usage data stale
- **WHEN** usage data goes stale and the idle view shows
- **THEN** the session list remains visible

#### Scenario: Boards without the flag
- **WHEN** firmware runs on a board with `has_session_list` false
- **THEN** no session UI is created and the screen is unchanged from before this change
