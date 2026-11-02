# Design: `agy` (Antigravity CLI) as a shantytown harness

Status: DESIGN for review. Nothing here is implemented.

Scope: run crew on Gemini through the Antigravity CLI (`agy`). The same
harness also gives st one-shot, paneless review and review-fix jobs.

Reference version: `agy` 1.4.12.

The headless behaviour is measured from the Gemini reviewer pilot: about 40
one-shot reviews on 2026-11-01 and 2026-11-02. The interactive pane behaviour is
NOT measured yet. Phase 0 below measures it before any code depends on it.

## Goals and acceptance

1. One crew agent runs an ordinary dispatch end to end on `agy`. The item goes
   from assignment to PR, and the stop event is drained, with the live process
   verified the way st verifies `claude` and `codex` today.
2. One headless review job posts a PR verdict.
3. The governor reads `agy` usage and refuses work when the quota is exhausted.

## What `agy` offers (measured from 1.4.12, `--help` and its built-in docs)

| Need | `agy` surface |
|---|---|
| Interactive pane | `agy` (TUI); `--model`, `--effort`, `--mode accept-edits\|auto\|plan`, `--dangerously-skip-permissions`, `--sandbox` |
| One-shot | `--print=` (attached, empty) with `--input-format stream-json --output-format stream-json`; `--print-timeout <dur>` |
| Per-session settings | `--settings <json or file>`: session-only and never saved. It takes the keys that `settings.json` accepts. |
| Hooks | `hooks.json` in a customization root: the global root, or `.agents/` in the workspace. Events are `SessionStart`, `PreToolUse`, `PostToolUse` (with tool-name `matcher`), `PreInvocation`, `PostInvocation` and `Stop`. Commands run through `sh -c`, take JSON on stdin and return JSON on stdout, synchronously, with a default timeout of 30 s. |
| Blocking stop | A `Stop` handler returning `{"decision":"continue","reason":…}` re-enters the loop with `reason` as a system message. The payload carries `terminationReason` and `fullyIdle`. |
| Tool guard | `PreToolUse` returns `decision` = `allow`, `deny`, `ask` or `force_ask`. It can also return `overwrite`, a shallow merge into the tool arguments. |
| Context injection | `SessionStart` and `PreInvocation` return `injectSteps`: a `systemMessage`, `userMessage` or `ephemeralMessage`. |
| MCP | `agy mcp add\|remove\|list\|enable\|disable`; `mcp_config.json` in the global config root or in a plugin. |
| Skills, agents, rules | `skills/` (SKILL.md), `agents/` and `rules/AGENTS.md` under a customization root or a plugin. `agy plugin import claude` converts Claude Code plugins. |
| Auth | One OAuth token file in the user's `agy` data dir. `agy` creates everything else it needs on first run. |
| Own safety layer | A built-in "PolicyGuardian" model audits irreversible actions, and a sandbox restricts the terminal. Neither replaces st guards; see Hooks. |

## Design

### 1. Registry and card admission

- Add `AgyHarness` to the harness registry (`harness._HARNESSES`). Like
  OpenCode, keep it in its own module (`shantytown/agy.py`) and register it
  through a factory. `UnknownHarness` and `Unsupported` handling stays as it is.
- A crew card with `"harness": "agy"` is admitted through the existing
  `get()`/`name_for()` path.
- `[harness] required_by_role` keeps working unchanged.
- Admission refuses `agy` for any role whose `HookSpec` needs a blocking stop
  until Phase 2 proves the `Stop` hook live. Until then, `agy` is
  `blocking_stop=False`, like `opencode`, so it can be a worker, never a lead or
  administrator.
- Name enumerations that must learn `agy`:
  - `hook_bundles.HARNESSES` and the per-format readers;
  - `accounts` (allowed harnesses, the credential filename);
  - `crew_credentials`;
  - `job_launch` (unattended allowlist; see 5);
  - `doctor` tool rows;
  - CLI help text (`st agent spawn --harness`, `st agent harness`).
- Fix found during the survey, needed before `agy` can be a fleet default:
  `provision.py` reads `card.harness` directly. A card that inherits its harness
  from `[harness] default` or `by_role` is therefore provisioned as `claude`.
  Use `harness.name_for()` there. This is a separate small fix, independent of
  `agy`.

### 2. Launch, settings and the live-process proof

- `launch()` builds this command:

  ```text
  cd <workspace> && env <identity vars> agy [--model M] [--effort E]
      [--dangerously-skip-permissions] --settings <root>/settings/agy/<role>.settings.json
  ```

  - The identity variables are the same set every harness gets (`SHANTY_AGENT`,
    `BEADS_ACTOR`, `ST_ROLES`, `SHANTY_ROOT`, `SHANTY_MODEL`, …).
  - `chrome` raises `Unsupported`.
- The `--settings` path is on argv. `settings_in_cmdline` reads it back from the
  running process, the same way claude's `--settings` is recovered.
  `settings_env_var` is `None`.
- Hooks do not go through `--settings`. `agy` loads them from `hooks.json` in a
  customization root, so st renders them per agent into
  `<workspace>/.agents/hooks.json`:
  - The global root is shared by every `agy` process for the user. Writing st's
    hooks there would apply one role's hooks to every agent, including the
    operator's own `agy` sessions. The global file is therefore never written.
  - Each crew agent already has its own workspace, so per-workspace hooks give
    per-agent hooks with no shared state.
  - `.agents/` is added to the workspace's git exclude, as st already does for
    its other workspace files.
- `read_stop_directions` and `read_bash_guard` parse that `hooks.json`. They
  return `None` ("cannot tell") when the file is missing or malformed, never
  "no guard".
- Proving the live process is the open question.
  - `--settings` on argv proves which settings the process took.
  - It does not prove the process loaded the workspace `hooks.json`, which is
    read at session start.
  - The proof therefore pairs two observations:
    - (a) the `hooks.json` bytes at launch, recorded with their sha256, as
      `hook_bundles.apply_live` already does for claude;
    - (b) a `SessionStart` hook that writes a receipt to the agent's st state
      dir. The receipt holds `conversationId`, `workspacePaths` and the sha256 of
      the `hooks.json` it ran from.
  - No receipt within the ready window means the hooks are "not proven", and the
    agent is not marked hook-ready. A receipt whose sha does not match (a) is
    drift.
- Instruction file:
  - `agy` reads `rules/AGENTS.md` from a customization root, and workspace-level
    `AGENTS.md`/`GEMINI.md`. Which of the workspace files 1.4.12 reads is
    measured in Phase 0.
  - `link_instructions` points whichever file it reads at the same `AGENTS.md`
    symlink that codex and opencode use.

### 3. Hooks: parity with claude and codex

| st hook | `agy` mapping |
|---|---|
| Stop: send and drain | A `Stop` handler runs the existing `st` stop command. To block a stop for a drain it returns `{"decision":"continue","reason":<drain text>}`; otherwise it returns `{}`. It runs only when `terminationReason` is `NO_TOOL_CALL` and `fullyIdle` is true. On `ERROR`, `USER_CANCELED` or a budget stop it records the event and never forces a continue, so a failed or cancelled turn cannot loop. |
| SessionStart | The same st session-start command, emitted as `injectSteps:[{systemMessage:{systemMessage:…}}]`, plus the receipt from 2(b). |
| Bash guard | `PreToolUse` with `matcher` `run_command`. It maps the guard's exit-2 refusal to `{"decision":"deny","reason":…}`, and pass to `{"decision":"allow"}`. It never uses `overwrite`: st guards refuse, they do not rewrite commands. |
| Pre-edit guard | `PreToolUse` with a matcher on the file-write tool names. The exact names come from Phase 0, because `agy` tool names are its step types, lower-cased. Until those names are measured, `read_pre_edit_guard` returns `None`, not `""`. |
| Prompt screen | `PreInvocation` is available, but st has no prompt hook today, so it is not mapped. |

- Every mapped hook is a thin adapter: `st hook agy <event>`. It translates the
  `agy` JSON payload to the existing st hook entry points and translates their
  result back. The guard logic itself is not duplicated.
- `agy` runs hooks synchronously with a 30 s default timeout. Long st work (the
  drain read, the inbox) keeps the bounded timeouts it already has, and the
  adapter declares `timeout` explicitly.
- `agy`'s own PolicyGuardian and sandbox stay on. They are an extra layer, not a
  substitute: st guards are the policy of record, and a PolicyGuardian refusal
  is terminal for that action, like any other policy refusal.
- `--dangerously-skip-permissions` follows the card's existing `dangerous` flag
  exactly as for claude. It skips `agy`'s permission prompts only; hooks still
  run.

### 4. MCP, skills and provisioning

- `st provision` projects the same server set that claude and codex get (quipu,
  bobbin, yupana).
  - The `agy` format is written per agent with `agy mcp add`, under
    `HOME`-scoped config: the CLI is the supported writer, and st does not
    hand-edit `agy`'s state files.
  - If `agy mcp add` turns out to be user-global only (Phase 0), the servers are
    rendered into a per-workspace plugin under `.agents/plugins/st/`, which also
    gives `mcp_config.json` per agent.
- Skills: the provisioned skill dirs are linked into
  `<workspace>/.agents/skills/`, the same pattern codex uses for
  `.agents/skills`.
- Drift detection reuses the existing kit-gap check with an `agy` translator, in
  the same shape as `opencode.translate_servers`.

### 5. Headless jobs (review and review-fix)

- This is new: no harness has a paneless one-shot mode today. Ephemeral jobs are
  tmux panes. The job type is `st job agy-review` (and later `agy-fix`). It owns
  the command builder; the pilot's scratch scripts are the reference behaviour,
  ported, not wrapped.
- Invocation (measured):

  ```text
  agy --print= --input-format stream-json --output-format stream-json
      --model <M> --sandbox --disable-slash-commands --print-timeout <T>
  stdin: one line {"event":"user","message":{"content":"<prompt>"}}
  ```

  - cwd is a fresh empty dir, checked empty again afterwards.
  - `PATH` is minimal.
  - The outer hard timeout is `T` + 60 s.
- HOME and credentials:
  - Each job runs with `HOME` set to a private scratch dir (0700).
  - It holds ONLY a copied 0600 auth token file: never a symlink, never the real
    `HOME`.
  - The token copy and the scratch dir are deleted when the job ends, on every
    exit path. The agent-created files there hold conversation history.
  - The token path is found by presence, never read by st.
- Result contract: a job has a verdict only when ALL of these hold:
  - the `init` event names the served model (recorded; a mismatch with the
    requested model is recorded and refused);
  - a `result` event exists with a non-empty `response`;
  - the response parses as the rubric's JSON after stripping ``` fences.
- Anything else is "no verdict", whatever `status` says. Two measured shapes
  show why:
  - `status` SUCCESS with an empty response and `finished_reason`
    `print_timeout`;
  - `status` ERROR with stderr "print timeout … returning partial output".
- Quota failure:
  - The quota error is detected by its type: `AGY_ERROR` with
    `status` `RESOURCE_EXHAUSTED` or `error_code` 429. Elapsed time is not used.
  - The first one stops the whole batch. `agy` marks it `"retryable": true`,
    but the reset is days away.
  - The "Resets in <duration>" text goes to the governor (see 6).
  - There is no automatic retry of any job.
- Concurrency: jobs that share one `agy` account (one token) run one at a
  time, under a per-account lock in the st state dir. The quota is per account,
  so parallel jobs would only reach the cap sooner and make the 429 ambiguous.
- Untrusted input: the PR body and diff are data. The model runs sandboxed and
  tool-less in an empty dir, and the rubric says so.
- Posting:
  - Posting is a separate step after the verdict.
  - It refuses if the PR head moved since the review, or if the PR is not open.
  - It scrubs internal identifiers before any public post.
  - A review verdict does not bypass review gates; see "Review identity"
    below.
- Review identity (open decision):
  - The native review gate (`pr-risk review`) takes the crew caller as the
    reviewer.
  - An `agy` job has no crew identity of its own, so its verdict cannot be
    recorded as a native review by itself. Two options:
    - **A. Advisory plus crew review (works today).** The `agy` verdict is
      posted as advisory feedback. A non-author crew reviewer validates it
      against the source and records the native review under their own
      identity. Blocking `agy` findings must still be resolved or answered.
    - **B. Operator-bound `agy` identity.** A named reviewer identity such as
      `agy@<operator>` is admitted to the review policy, so the job's verdict
      records natively. Changing who may sign reviews is a deliberate
      administrator action recorded on the decision desk. It also needs the
      attribution rules: never the author, never the dispatching author's own
      account.
  - Recommendation: ship Phase 1 with A, and take B to the administrator as a
    separate decision. A is what the gate admits now, and B changes review
    authority, which this design must not do on its own.
- Unattended (protected-UID) jobs stay refused while
  `ephemeral.unattended_uid_ready` is false. The headless job runs attended,
  under the dispatching operator's identity, and `job_launch`'s allowlist gains
  `agy` only for this job type.

### 6. Governor and cost

- The quota is per individual account. In the one observed exhaustion, 32
  one-request reviews used it up and the 429 reported a reset about 6.6 days
  away. The planning figure of 100 per day was wrong.
- The window's shape is NOT measured: fixed weekly, rolling, or something else.
  The source records every 429's reported reset time, so the shape can be
  learned from data. Until then the rolling 7-day count is a heuristic, not the
  quota's real definition.
- `agy` exposes no remaining-quota figure in headless output.
- New governor source `agy_events`. It reads the job result files and pane
  session records:
  - It counts model requests (`num_turns`) over a rolling 7 days.
  - It sums `usage` tokens: input, output, thinking and cache.
- The only authoritative "exhausted" signal is the 429 text "Resets in <dur>".
  The source turns it into an exhausted-until timestamp, and the governor
  refuses `agy` dispatch until then.
- Without a 429, remaining quota is UNKNOWN, never assumed full. The configured
  soft cap (`[governor.by_harness.agy] weekly_requests`, default 30) is advice,
  not a measurement.
- Per-item cost (cost model work): tokens are measured; dollar price is UNKNOWN
  unless a published price table is configured. No invented price.
- Interactive panes: per-request usage comes from the session's conversation
  record if Phase 0 finds a readable one. Otherwise pane usage is UNKNOWN and
  only the 429 gates.

### 7. Composer and input handling

- st's composer guards are per harness: ready, picker and stranded markers, and
  submission verification. `agy`'s TUI is not measured, so `agy` starts with
  empty marker tuples.
- With empty markers, `send()` falls back to the generic checked `deliver()`:
  type, see, Enter, see the turn start. This is what opencode does today.
- Phase 0 records the TUI's paste placeholder, ready line and in-turn status
  line. It adds them as markers only from those measurements, together with a
  stranded-input test like the codex one. Until then, `agy` panes are not
  eligible for st's stranded-input auto-clear. They are reported, not cleared.

### 8. Doctor and docs

- `st doctor` gets an `agy` row with these checks:
  - version;
  - auth present (by presence);
  - `hooks.json` present and parseable for each `agy` agent;
  - last SessionStart receipt age;
  - quota state from the governor (`ok`, `exhausted until T`, or `unknown`).
- `docs/harnesses.md` gains an `agy` section covering the card, config, files on
  disk and what does not work yet.

## Phases

| Phase | Work | Exit gate |
|---|---|---|
| 0 Measure | One attended `agy` pane in a scratch workspace with a minimal `hooks.json`. Record: which instruction files load; the tool names for edits; the `Stop` and `SessionStart` payloads; the TUI markers; whether `agy mcp add` is global or per workspace; where session usage is recorded. No crew card changes. | A recorded table of the measurements. |
| 1 Headless job | `st job agy-review` with the result contract, the scratch-HOME token copy, the per-account lock, quota stop and posting guards. Port the pilot's tests as fixtures. Review identity option A. | One real review job posts an advisory verdict on a PR, and a crew reviewer records the native review. A forced 429 fixture stops the batch. |
| 2 Pane harness | `AgyHarness`, the hooks adapter, the SessionStart receipt, provisioning and doctor. `blocking_stop` turns True only after the live Stop drain is proven. | One worker card on `agy` completes item → PR → stop drained. The doctor row is green. |
| 3 Governor | The `agy_events` source, 429 exhaustion and the soft weekly cap. | The governor shows `agy` usage, and refuses dispatch while exhausted. |

Phases 1 and 2 are independent and can be reviewed separately. Phase 3 needs
the result records from 1 and the session records from Phase 0.

## Risks and how each is handled

- A per-user global config leaking between agents: st writes only
  per-workspace `.agents/` files and never the global root.
- Quota exhaustion mid-batch: there are about 30 requests a week, so a careless
  batch burns the week. Jobs on one account are serialized, the batch stops on
  the first 429, and the governor soft cap advises before that.
- A `Stop` hook looping: `continue` is returned only for the normal-completion
  reason with `fullyIdle`. `agy` also caps forced continuations
  (`MAX_FORCED_INVOCATIONS`).
- Trusting `status`: verdicts need a parsed response. `status` is recorded,
  never used to decide.
- Hooks not loaded: the SessionStart receipt is the proof. Without it the agent
  is not hook-ready.
- Hiding st's own guard: `agy`'s PolicyGuardian may refuse first. That is fine,
  because both refusals are terminal, and the st guard is still verified to be
  wired.

## Not in scope

- Remote control (`--remote-control`) and the microphone server.
- Browser/chrome.
- `agy` plugins beyond the st-rendered per-workspace one.
- Account switching.
- Making `agy` a lead or administrator before its blocking stop is proven.
