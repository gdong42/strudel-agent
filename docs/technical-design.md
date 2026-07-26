# Technical Design: Strudel Agent

## 1. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend build | Vite (vanilla-ts template) | Fast HMR, simple config, no framework overhead |
| Frontend language | TypeScript (strict) | Strong browser-side contracts around REPL adapter and UI state |
| Frontend | Vanilla TS + `@strudel/repl@1.3.0` web component | Thin adapter over the REPL, no UI framework dependency |
| Backend | Python 3.12 + FastAPI | Better long-term fit for users, auth, database, background jobs, deployment, and model/API integrations |
| Backend validation | Pydantic | API schemas, config validation, and provider response validation |
| Transport | SSE (server→client) + HTTP POST (client→server) | Run status and track updates are server-driven; user intents, clarification answers, and controls are commands |
| Diff render | CodeMirror merge extension or hand-rolled inline diff | CodeMirror is already in the REPL; reuse its extension ecosystem |
| API contracts | FastAPI OpenAPI schema + generated or hand-maintained TS types | Backend owns validation; frontend consumes stable HTTP contracts |
| Agent runtime | Python Agent Run state machine + tool registry | The product owns iteration, tools, budgets, pause/resume, and finalization |
| Agent providers | Model-turn adapters over direct APIs | Normalize messages and tool calls without tying the runtime to one vendor |
| Config | `project.config.json` (JSON, loaded by backend at startup) | Human-writable, no env-var sprawl |

## 2. Delivery Model

The first implementation is a local-first workspace app.

- The user runs the frontend and backend on their own machine.
- The backend is a local runtime backend for the current workspace, not a shared hosted service.
- The current project maps to a local directory containing tracks, snapshots, changes, samples, config, and agent context.
- The current session maps to the active browser/backend runtime state for that project.
- No user account, cloud storage, multi-tenant permissions, billing, or hosted model-key custody is required in the first product version.

Use explicit `project_id` and `session_id` fields in API/state models where useful, but treat them as local identifiers for now. This keeps the design portable to a future hosted app without paying the hosted complexity cost during the product-validation phase.

## 3. Architecture Layers

```text
┌─────────────────────────────────────────────────┐
│  Browser                                         │
│  ┌──────────────┐  ┌───────────┐  ┌───────────┐ │
│  │ REPL adapter │  │ Agent UI  │  │ Recovery  │ │
│  │ (repl.ts)    │  │ (panel,   │  │ (state,   │ │
│  │              │  │  diff,     │  │  revert)  │ │
│  │              │  │  staging)  │  │           │ │
│  └──────┬───────┘  └─────┬─────┘  └─────┬─────┘ │
│         │                │               │       │
│  ┌──────┴────────────────┴───────────────┴──────┐│
│  │  Client event bridge (SSE + HTTP)            ││
│  └──────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
                        │
┌───────────────────────┼─────────────────────────┐
│  Server               │                          │
│  ┌──────────┐  ┌──────┴─────┐  ┌──────────────┐ │
│  │ Files    │  │ Agent Run  │  │ Snapshots    │ │
│  │ (track   │  │ Runtime    │  │ / History    │ │
│  │  I/O)    │  └─────┬──────┘  │              │ │
│  └──────────┘        │         └──────────────┘ │
│                 ┌────┴─────┐  ┌──────────────┐  │
│                 │ Tool     │  │ Model-turn   │  │
│                 │ Registry │  │ Providers    │  │
│                 └──────────┘  └──────────────┘  │
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │  HTTP + SSE endpoints                        ││
│  └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

## 4. REPL Adapter Interface

```typescript
// src/client/repl.ts

interface ReplAdapter {
  // Core
  getCode(): string;
  setCode(code: string): void;
  evaluate(): Promise<void>;
  stop(): void;

  // Cursor / selection
  getCursor(): { line: number; ch: number };
  getSelection(): string;

  // State
  isDirty(): boolean;
  onUpdate(callback: (code: string) => void): void;
}
```

The adapter wraps `strudel-editor.repl.editor` (CodeMirror instance). All DOM access and `waitForEditor()` polling stays inside this module.

## 5. State Machine

### 5.1 Core States

```
projectId        — local workspace identifier
sessionId        — current browser/backend runtime session identifier
activeCode       — last successfully evaluated code (currently performing)
editorCode       — code visible in the REPL editor
lastGoodCode     — most recent known safe fallback
preAgentCode     — editor contents immediately before latest agent stage
changeSet        — metadata for latest agent-staged change
```

### 5.2 State Transitions

| Event | activeCode | editorCode | lastGoodCode | preAgentCode | changeSet |
|---|---|---|---|---|---|
| **Manual evaluate (success)** | ← editorCode | (unchanged) | ← editorCode | (unchanged) | (cleared) |
| **Manual evaluate (failure)** | (unchanged) | (unchanged) | (unchanged) | (unchanged) | (unchanged) |
| **Completed Agent Run stages** | (unchanged) | ← final agent output | (unchanged) | ← previous editorCode | ← final agent metadata |
| **Agent undo** | (unchanged) | ← preAgentCode | (unchanged) | (cleared) | (cleared) |
| **Manual edit** | (unchanged) | ← user input | (unchanged) | (unchanged) | (unchanged) |
| **Revert to lastGood** | ← lastGoodCode | ← lastGoodCode | (unchanged) | (cleared) | (cleared) |

### 5.3 Evaluation Rules

1. `Manual Fire` (default): a completed run stages into the editor, then the user presses Ctrl+Enter to evaluate.
2. `Auto Fire` (opt-in): a completed run stages and evaluates only after deterministic finalization gates pass.
3. Failed evaluation MUST NOT overwrite `lastGoodCode`.
4. Failed evaluation MUST NOT stop the currently running scheduler.
5. `Stop` halts playback and disables Auto Fire.
6. `Panic` stops playback, clears visuals, and presents a confirm dialog before optionally reloading the REPL iframe.

### 5.4 Agent Run State

Agent work-in-progress is separate from editor and performance state:

```text
runId             — identifier for one user intent and its internal work
runStatus         — running | needs_input | completed | failed | cancelled
baseCode/hash     — editor version the run currently reasons against
turns             — normalized model messages and tool results needed to continue
budgets           — turn, elapsed-time, token, and cancellation limits
finalChange       — present only after successful finalization
pendingQuestion   — present only while needs_input
```

Candidate code, validation findings, and recoverable tool errors remain inside
the run. They do not update `editorCode`, create a `changeSet`, or enter change
history. A completed run crosses the staging boundary exactly once: its final
change is compared with the latest editor version, staged, and then handled by
Manual Fire or Auto Fire.

`needs_input` is not a failed validation state. The agent may use it only when
the user's intent is materially ambiguous, constraints conflict, or a creative
decision cannot be made responsibly without the user. Answering resumes the
same run with the latest editor version.

## 6. Agent API Contract

### 6.1 Agent Code Model Decision

**Agent operates directly on Strudel JS**, not on a higher-level song model that compiles to Strudel.

Rationale:
- The editor content is the source of truth; agent must produce valid Strudel JS to be useful.
- A song-model layer adds indirection that makes diff/review harder (user sees compiled code, not intent).
- Advanced users need to inspect and edit agent output directly.
- Revisit the song-model approach only if the agent consistently produces structural errors that a model layer would prevent.

### 6.2 Change Format Decision

**Full-file replacement with a structured diff computed on the client.**

Rationale:
- Full-file is simpler for the agent to generate.
- The client computes the diff for display using the CodeMirror merge extension.
- `preAgentCode` + `editorCode` gives us the before/after pair needed for diff.

### 6.3 Provider Strategy

The product calls model APIs through narrow model-turn adapters instead of
binding the workflow to a platform-specific agent SDK.

Rationale:
- We need to support multiple model and API vendors over time.
- The app owns the Agent Run, tool execution, budgets, pause/resume,
  finalization, staging, fire control, snapshots, and recovery.
- Providers map normalized messages and tool definitions to vendor APIs, then
  normalize assistant output and tool calls back to the runtime.
- A provider must not decide when an internal candidate is final or stage code
  directly into the editor.
- Vendor SDK agent loops may be evaluated inside adapters later, but only if
  they preserve the same run/tool/finalization contract.

```python
@dataclass(frozen=True)
class ModelTurnRequest:
    messages: list[AgentMessage]
    tools: list[ToolDefinition]
    model: str
    remaining_token_budget: int

class AgentProvider(Protocol):
    async def next_turn(self, request: ModelTurnRequest) -> ModelTurnResult:
        ...
```

`ModelTurnResult` contains normalized assistant content, tool calls, usage, and
provider metadata. The runtime, not the adapter, decides whether to execute a
tool, continue the loop, pause for user input, fail, or accept a finalized
change.

The current `create_change()` adapters are a transitional one-shot
implementation. They remain usable while P4C introduces `next_turn()` and moves
generation control into the runtime.

Current providers remain direct API integrations:

- OpenAI uses the Responses API and `gpt-5.6-terra` by default.
- DeepSeek uses Chat Completions and `deepseek-v4-pro` as the checked-in
  project default.
- Mock remains deterministic for runtime and UI tests.

Each adapter will normalize its vendor's native tool-call representation into
the shared model-turn contract. Provider settings and browser-supplied API-key
handling remain unchanged.

### 6.4 Agent Instructions And Tools

`backend/app/prompt_contract.py` owns the vendor-neutral system prompt, JSON
input conventions, and final-change schema. As the runtime becomes tool-driven,
the prompt instructs the model to pursue the user's intent, use available tools
to inspect and validate its work, revise recoverable problems internally, and
finish only when it judges the result ready.

Initial runtime tools:

- `inspect_diff(base_code, candidate_code)`: return a deterministic diff for
  the agent's self-review.
- `validate_candidate(candidate_code)`: run available non-performing syntax,
  mini-notation, sample, structural, and safety checks.
- `finalize_change(code, explanation, warnings)`: request completion. The
  runtime applies deterministic finalization gates before accepting it.
- `request_user_input(question, options, reason)`: pause only for material
  ambiguity, conflicting constraints, or a key user decision.

Tool results are observations for the agent, not user-facing workflow states.
If `inspect_diff` shows that a candidate changed bass despite "only change
drums," the agent is expected to revise and check again. It must not finalize
that intermediate result and ask the user to adjudicate the agent's own error.

The runtime controls budgets and safety boundaries, but it does not hardcode a
domain-specific sequence such as "generate, then check drums, then regenerate."
The model chooses its tool calls and revision strategy. Configurable turn,
elapsed-time, token, and cancellation budgets prevent runaway loops. Exhausting
a budget ends the run as `failed`; no internal candidate is staged.

### 6.5 Agent Run Lifecycle

```text
user intent + current editor version
                │
                ▼
             running
                │
      model turn / tool call loop
       ┌────────┼──────────────┐
       │        │              │
 recoverable   material      finalized
 finding       ambiguity      candidate
       │        │              │
       │        ▼              ▼
       │   needs_input    finalization gates
       │        │          ├─ fail → tool result → running
       │   user answer     └─ pass → completed
       │        │                         │
       └────────┴────────► running        ▼
                                   stage final change
```

Only public boundary states cross into the user-facing workflow:

- `completed`: stage the final change and show its final explanation/diff.
- `needs_input`: show one concise clarification or decision request, then
  resume the same run after the answer.
- `failed`: explain that the run could not complete; keep editor and playback
  unchanged.
- `cancelled`: keep editor and playback unchanged.

Normal candidate failures, scope violations, tool errors that can be repaired,
and self-review notes remain internal. Hidden model reasoning is neither
requested nor persisted.

### 6.6 Agent Run API

```text
POST /agent/runs                 Start a run from user intent + editor version
GET  /agent/runs/:id             Read public run status
POST /agent/runs/:id/input       Answer a needs_input question
POST /agent/runs/:id/editor      Supply a newer editor version to the run
POST /agent/runs/:id/cancel      Cancel the run
GET  /events                     Stream public run status and final results
```

```python
class AgentRunPublic(BaseModel):
    id: str
    status: Literal["running", "needs_input", "completed", "failed", "cancelled"]
    question: AgentQuestion | None = None
    final_change: AgentFinalChange | None = None
    error: AgentRunFailure | None = None
```

The public representation excludes internal candidates, recoverable findings,
raw provider messages, and hidden reasoning. Run audit records may retain user
messages, tool names, tool outcomes, usage, final result, and provider metadata,
but never credentials or hidden chain-of-thought.

Concurrent editing becomes a run-context update. Before final staging, the
browser and runtime compare editor hashes. A newer editor version is supplied to
the active run, which reconciles and self-reviews again. The current fixed
two-request client reconciliation remains only until this run API replaces it.

### 6.7 Finalization And Fire Safety

`finalize_change` is a request from the agent, not an unconditional commit.
Deterministic gates reject empty code, unsafe dynamic execution, invalid syntax
where tooling is available, and stale editor versions. Rejections become tool
results and return control to the agent while budgets remain.

Final warnings are reserved for irreducible limitations or risks that the agent
cannot verify or remove. They are not a channel for exposing intermediate scope
violations. A run with unresolved blocking risk cannot complete or Auto Fire.
Manual Fire remains the default; Auto Fire is allowed only after a completed run
passes all deterministic gates and has not been invalidated by concurrent user
editing.

## 7. Module Responsibilities

### 7.1 Server Modules

| Module | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI app setup, route registration, SSE management |
| `backend/app/models.py` | Pydantic request/response/project/session state models |
| `backend/app/tracks.py` | Track file I/O (read from `tracks/`, write to `tracks/`) |
| `backend/app/snapshots.py` | Snapshot CRUD, pruning (keep last 50 or 24h) |
| `backend/app/changes.py` | Persist, list, and undo completed final changes only |
| `backend/app/agent_runtime.py` | Agent Run lifecycle, budgets, model turns, pause/resume, and finalization |
| `backend/app/agent_runs.py` | Run state storage and public run projections |
| `backend/app/prompt_contract.py` | Shared agent instructions and final-change schema |
| `backend/app/tools/` | Tool registry and deterministic tool implementations |
| `backend/app/providers/` | Vendor-specific model-turn and tool-call adapters |
| `backend/app/samples.py` | Sample registry used by internal validation tools |
| `backend/app/config.py` | Load and watch `project.config.json` |

### 7.2 Client Modules

| Module | Responsibility |
|---|---|
| `client/repl.ts` | `strudel-editor` adapter (see §4) |
| `client/agent.ts` | Intent, public run status, clarification, and Manual/Auto Fire UI |
| `client/diff.ts` | Diff computation and inline/side-by-side rendering |
| `client/state.ts` | Client-side state machine (§5), transition guards |
| `client/recovery.ts` | Revert to `lastGoodCode`, error display, panic handler |
| `client/status.ts` | Connection, public run status, evaluation status, errors, and final warnings |
| `client/settings.ts` | Browser-local provider/model settings and API-key storage policy |
| `client/bridge.ts` | SSE listener, run commands, HTTP helpers, reconnect logic |
| `client/main.ts` | App bootstrap, glue |

## 8. API Endpoints

```text
GET  /events                     SSE stream (track updates, agent notifications)
POST /track                      Save editor code to disk (from evaluate)
GET  /state                      Current local project/session runtime state
GET  /agent/settings             Provider defaults and installed provider capabilities
POST /agent/providers/test       Test transient browser-supplied provider settings
POST /agent/runs                 Start an Agent Run
GET  /agent/runs/:id             Read public run status
POST /agent/runs/:id/input       Answer a clarification
POST /agent/runs/:id/editor      Supply a newer editor version
POST /agent/runs/:id/cancel      Cancel a run
GET  /changes/latest             Get latest staged change metadata
POST /changes/:id/undo           Undo a staged change (restore preAgentCode)
GET  /snapshots                  List snapshots
POST /snapshots                  Create snapshot after successful evaluate
POST /snapshots/:id/revert       Revert to a snapshot
GET  /samples                    List known samples
```

## 9. File Layout (Revisited)

```text
.
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── agent_runtime.py
│   │   ├── agent_runs.py
│   │   ├── prompt_contract.py
│   │   ├── changes.py
│   │   ├── tracks.py
│   │   ├── snapshots.py
│   │   ├── samples.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── diff.py
│   │   │   ├── validation.py
│   │   │   └── finalization.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── http.py
│   │       ├── openai.py
│   │       ├── deepseek.py
│   │       └── mock.py
│   └── tests/
├── src/
│   └── client/
│       ├── main.ts
│       ├── repl.ts
│       ├── agent.ts
│       ├── diff.ts
│       ├── state.ts
│       ├── recovery.ts
│       ├── status.ts
│       ├── settings.ts
│       └── bridge.ts
├── tracks/
│   └── main.strudel.js
├── snapshots/
├── changes/
├── samples/
├── project.config.json
├── agent-context.md
├── TODO.md
├── docs/
│   ├── live-vibe-coding-plan.md
│   └── technical-design.md
├── index.html                    # POC reference; replaced by Vite entry
├── package.json
├── tsconfig.json
├── vite.config.ts
└── uv.lock
```

## 10. project.config.json Schema

```json
{
  "trackFile": "tracks/main.strudel.js",
  "snapshots": {
    "maxCount": 50,
    "maxAgeHours": 24
  },
  "agent": {
    "provider": "deepseek",
    "model": "deepseek-v4-pro",
    "contextFile": "agent-context.md",
    "runtime": {
      "maxTurns": 8,
      "maxElapsedSeconds": 90,
      "maxTotalTokens": 50000
    }
  },
  "samples": {
    "registryPath": "samples/"
  },
  "server": {
    "host": "127.0.0.1",
    "port": 8787
  }
}
```

The config file supplies backend defaults. The settings UI can override provider
and model in the current browser. API keys are stored only in browser storage and
sent to the backend for the duration of an individual request; the backend must
not persist or return them. A hosted deployment may use platform credentials when
the browser does not supply a user key.

Runtime limits are operational guardrails, not a hardcoded task plan. The agent
still chooses which tools to call and when to revise; the limits only prevent
unbounded cost and latency. Values are initial defaults and should be tuned with
evaluation data.

## 11. agent-context.md Format

A user-editable markdown file injected into the agent's system prompt. Expected sections:

```markdown
# Project Context

## Musical Style
(BPM range, genre, mood, preferred keys/scales)

## Instrument Roles
- drums: (what samples, typical patterns)
- bass: (synth type, range, role)
- chords: (voicing preferences)
- pad: (texture role)
- lead: (when to use, what synth)
- fx: (reverb, delay, filter preferences)

## Arrangement Conventions
(section markers, transition patterns, energy curve)

## Constraints
(things the agent should never change, sample name conventions)
```

## 12. Testing Strategy

### Automated

| Target | What to test |
|---|---|
| Client state transitions (Vitest) | Each transition in §5.2; verify state invariants hold |
| REPL adapter unit boundaries (Vitest) | Adapter behavior around `setCode`, dirty state, and event callbacks |
| Agent Run transitions (pytest) | running/needs_input/completed/failed/cancelled, resume, cancellation, and budget exhaustion |
| Finalization invariants (pytest) | Only completed final changes reach editor/history; stale and invalid candidates return to the loop |
| Tool registry (pytest) | Validate arguments/results, tool failures, diff inspection, and non-performing candidate checks |
| Provider adapters (pytest) | Verify normalized messages, tool definitions, tool calls, usage, and API error mapping |
| Public run projection (pytest) | Ensure candidates, recoverable findings, credentials, and hidden reasoning are never exposed |
| Snapshot pruning (pytest) | Verify maxCount and maxAgeHours are respected |
| Config loading (pytest) | Parse valid config, reject invalid, apply defaults |

### Manual / Integration

| Target | What to test |
|---|---|
| REPL adapter | Verify setCode/getCode/evaluate/stop work through the actual `@strudel/repl` web component |
| Failed evaluate safety | Confirm a syntax error does not stop the running scheduler (targeted test from open question) |
| Visual feedback UX | Verify `punchcard`, `spiral`, `pianoroll`, `scope` render correctly and don't block audio |
| Agent self-correction | Confirm recoverable validation failures cause another internal turn, not a staged/user-facing candidate |
| Clarification flow | Confirm only a question is shown, the same run resumes, and no candidate reaches the editor |
| Auto Fire validation | Confirm only completed, current, deterministic-gate-passing results can auto-evaluate |
| Panic flow | Confirm panic stops audio, clears visuals, confirms before reload |

## 13. Current Target Decisions

Current implementation decisions:

1. **Agent code model**: Agent operates directly on Strudel JS (see §6.1).
2. **Change format**: Full-file replacement with client-side diff (see §6.2).
3. **Agent runtime ownership**: The backend owns a vendor-neutral Agent Run and tool loop; providers implement model turns, not the product workflow.
4. **Internal correction**: Candidate code, recoverable validation failures, and self-review remain internal until the agent produces a finalized result.
5. **Human-in-the-loop boundary**: User input is requested only for material ambiguity, conflicting constraints, or key creative decisions—not to repair the agent's intermediate mistakes.
6. **Final warning policy**: User-visible warnings are limited to irreducible final risks or unverifiable limitations. Recoverable findings must be handled inside the run.
7. **Bounded autonomy**: The model chooses tools and revisions, while configurable turn/time/token budgets prevent unbounded loops.
8. **Browser autosave**: Only on evaluate, not on debounce. The `dirty` flag is informational only; no silent disk writes.
9. **File sync model**: External file changes are broadcast through SSE. Agent candidates never enter the editor; only a completed final change stages into the editor, and `POST /track` writes visible code to disk on evaluate.
