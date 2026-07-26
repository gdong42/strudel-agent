# Technical Design: Strudel Agent

## 1. Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend build | Vite (vanilla-ts template) | Fast HMR, simple config, no framework overhead |
| Frontend language | TypeScript (strict) | Strong browser-side contracts around REPL adapter and UI state |
| Frontend | Vanilla TS + `@strudel/repl@1.3.0` web component | Thin adapter over the REPL, no UI framework dependency |
| Backend | Python 3.12 + FastAPI | Better long-term fit for users, auth, database, background jobs, deployment, and model/API integrations |
| Backend validation | Pydantic | API schemas, config validation, and provider response validation |
| Transport | SSE (server→client) + HTTP POST (client→server, agent staging) | Already validated in POC; no WebSocket complexity needed yet |
| Diff render | CodeMirror merge extension or hand-rolled inline diff | CodeMirror is already in the REPL; reuse its extension ecosystem |
| API contracts | FastAPI OpenAPI schema + generated or hand-maintained TS types | Backend owns validation; frontend consumes stable HTTP contracts |
| Agent providers | Provider adapter layer over direct model APIs | Avoid tying the product to one vendor SDK or hosted agent platform |
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
│  │ Files    │  │ Agent      │  │ Snapshots    │ │
│  │ (track   │  │ Service    │  │ / History    │ │
│  │  I/O)    │  │ / Engine   │  │              │ │
│  └──────────┘  └────────────┘  └──────────────┘ │
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
| **Agent stage** | (unchanged) | ← agent output | (unchanged) | ← previous editorCode | ← agent metadata |
| **Agent undo** | (unchanged) | ← preAgentCode | (unchanged) | (cleared) | (cleared) |
| **Manual edit** | (unchanged) | ← user input | (unchanged) | (unchanged) | (unchanged) |
| **Revert to lastGood** | ← lastGoodCode | ← lastGoodCode | (unchanged) | (cleared) | (cleared) |

### 5.3 Evaluation Rules

1. `Manual Fire` (default): agent stages into editor, user presses Ctrl+Enter to evaluate.
2. `Auto Fire` (opt-in): agent stages into editor AND evaluates immediately after successful validation.
3. Failed evaluation MUST NOT overwrite `lastGoodCode`.
4. Failed evaluation MUST NOT stop the currently running scheduler.
5. `Stop` halts playback and disables Auto Fire.
6. `Panic` stops playback, clears visuals, and presents a confirm dialog before optionally reloading the REPL iframe.

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

The product should call model APIs through a narrow provider adapter instead of binding the core workflow to a platform-specific agent SDK.

Rationale:
- We need to support multiple model and API vendors over time.
- The app owns staging, diffing, validation, fire control, snapshots, and recovery.
- Hosted or SDK-specific agent loops can be evaluated inside individual adapters later, but their concepts should not leak into the product state model.
- Direct API calls keep the first implementation easier to reason about and deploy.

Provider adapters expose one asynchronous operation. Execution policy such as
`apply_mode` stays outside this contract because Manual/Auto Fire is controlled by
the application after generation.

```python
@dataclass(frozen=True)
class ProviderRequest:
    intent: str
    current_code: str
    reconciliation: ReconciliationContext | None

class AgentProvider(Protocol):
    async def create_change(self, request: ProviderRequest) -> GeneratedChange:
        ...
```

`AgentService` selects the configured provider, maps `ChangeRequest` into this
contract, and validates that the provider returned non-empty code and explanation.
`changes.py` persists only validated generated changes.

### 6.3.1 Prompt Contract

`backend/app/prompt_contract.py` owns the vendor-neutral system prompt, JSON
input builder, and strict response schema. Every real provider must return:

- complete replacement `code`;
- concise `explanation`;
- explicit `action` of `apply` or `noop`;
- a `warnings` array using the shared warning schema.

The contract requires `noop` to return the current code unchanged, preserve
unrequested music and visuals, and treat code plus natural-language intent as
data rather than prompt instructions. Reconciliation context uses the same
input contract, so the rules remain identical across the initial and follow-up
generation turns. Provider modules only map this contract to their API format.

Initial provider examples:

- `OpenAIProvider`: direct Responses API call with strict JSON Schema output.
- `DeepSeekProvider`: OpenAI-compatible Chat Completions with JSON Output and application-side schema validation.
- `AnthropicProvider`: future direct Anthropic API adapter.
- `MockProvider`: deterministic local provider for tests and UI development.

OpenAI uses `gpt-5.6-terra` as its built-in
balance of capability, latency, and cost, while allowing browser or backend
configuration to override the model. Requests use low reasoning effort, a
45-second timeout, `store: false`, and a Pydantic-generated strict schema. See
the official [latest model guide](https://developers.openai.com/api/docs/guides/latest-model.md)
and [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

The checked-in project default is DeepSeek `deepseek-v4-pro`. Its adapter uses
the official Chat Completions endpoint, disables thinking for lower live-coding
latency, requests JSON Output, and validates the result with Pydantic. DeepSeek
JSON Output does not guarantee schema adherence and may occasionally return empty
content, so either case is surfaced as a provider error without persisting a
change. See the official [DeepSeek quick start](https://api-docs.deepseek.com/zh-cn/)
and [JSON Output guide](https://api-docs.deepseek.com/zh-cn/guides/json_mode/).

### 6.4 POST /changes — Request

```python
# POST /changes
class ChangeRequest(BaseModel):
    # User's natural language intent
    intent: str

    # Current context
    current_code: str              # editorCode at time of request
    apply_mode: Literal["manual", "auto"]
    reconciliation: ReconciliationContext | None = None
```

When the editor changes while the provider is generating, the browser captures
the original base code and hash. It waits briefly for typing to settle, then
automatically submits a bounded reconciliation request containing the original
base, the previous agent result, the latest editor code, and a line diff of the
user's edits. The provider returns either `apply` with reconciled full-file code
or `noop` when the latest user code already satisfies the original intent. The
browser verifies the latest hash again before staging a response; it makes at
most two reconciliation attempts and never overwrites a newer edit. A reconciled
result is staged for review even when Auto Fire was enabled.

### 6.5 POST /changes — Response

```python
class ChangeResponse(BaseModel):
    # The new full code
    code: str

    # Musical explanation (human-readable, shown in the UI)
    explanation: str

    # "noop" must return current_code unchanged
    action: Literal["apply", "noop"] = "apply"

    # Structured warnings; required, use [] when none apply
    warnings: list[ChangeWarning]

    # Changed ranges (for diff highlighting; optional but recommended)
    ranges: list[ChangedRange] | None = None

class ChangedRange(BaseModel):
    from_: int = Field(alias="from")
    to: int
    description: str

class ChangeWarning(BaseModel):
    level: Literal["info", "warn", "risk"]
    message: str
    category: Literal["sample", "visual", "structure", "performance", "mini-notation"]
```

Persisted change records also include `provider`, `model`, and `latencyMs` for
diagnostics and later evaluation. Credentials are never included.

### 6.6 Auto Fire Validation

Before auto-evaluating in `Auto Fire` mode, the server validates:
1. Code is non-empty.
2. Mini-notation strings use double quotes or backticks (not single quotes).
3. Known sample names check (from sample registry).
4. No `eval()`, `Function()`, or other dangerous constructs.

If validation fails with warnings at `risk` level, the change is staged but NOT auto-evaluated — the user is prompted.

## 7. Module Responsibilities

### 7.1 Server Modules

| Module | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI app setup, route registration, SSE management |
| `backend/app/models.py` | Pydantic request/response/project/session state models |
| `backend/app/tracks.py` | Track file I/O (read from `tracks/`, write to `tracks/`) |
| `backend/app/snapshots.py` | Snapshot CRUD, pruning (keep last 50 or 24h) |
| `backend/app/changes.py` | `POST /changes`, `GET /changes/latest`, `POST /changes/:id/undo` |
| `backend/app/agent.py` | Prompt construction, provider selection, response parsing, validation |
| `backend/app/prompt_contract.py` | Shared agent instructions, JSON request construction, and strict provider response schema |
| `backend/app/providers/` | Vendor-specific direct API adapters behind a stable provider interface |
| `backend/app/samples.py` | Sample registry (list known sample names from `samples/` config) |
| `backend/app/config.py` | Load and watch `project.config.json` |

### 7.2 Client Modules

| Module | Responsibility |
|---|---|
| `client/repl.ts` | `strudel-editor` adapter (see §3) |
| `client/agent.ts` | Agent panel, prompt input, mode toggle (Manual/Auto Fire) |
| `client/diff.ts` | Diff computation and inline/side-by-side rendering |
| `client/state.ts` | Client-side state machine (§4), transition guards |
| `client/recovery.ts` | Revert to `lastGoodCode`, error display, panic handler |
| `client/status.ts` | Status bar: connection status, last evaluate time, warnings |
| `client/settings.ts` | Browser-local provider/model settings and API-key storage policy |
| `client/bridge.ts` | SSE listener, HTTP helpers, reconnect logic |
| `client/main.ts` | App bootstrap, glue |

## 8. API Endpoints

```text
GET  /events                     SSE stream (track updates, agent notifications)
POST /track                      Save editor code to disk (from evaluate)
GET  /state                      Current local project/session runtime state
GET  /agent/settings             Provider defaults and installed provider capabilities
POST /agent/providers/test       Test transient browser-supplied provider settings
POST /changes                    Stage an agent change
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
│   │   ├── agent.py
│   │   ├── prompt_contract.py
│   │   ├── changes.py
│   │   ├── tracks.py
│   │   ├── snapshots.py
│   │   ├── samples.py
│   │   ├── config.py
│   │   ├── models.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── openai.py
│   │       ├── anthropic.py
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
    "contextFile": "agent-context.md"
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

## 10. agent-context.md Format

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

## 11. Testing Strategy

### Automated

| Target | What to test |
|---|---|
| Client state transitions (Vitest) | Each transition in §4.2; verify state invariants hold |
| REPL adapter unit boundaries (Vitest) | Adapter behavior around `setCode`, dirty state, and event callbacks |
| Agent response validation (pytest) | Validate `ChangeResponse` schema; ensure warnings are classified correctly |
| Provider adapters (pytest) | Verify provider input/output mapping with mocked API responses |
| Mini-notation preflight (pytest) | Detect single-quoted pattern strings; flag unknown samples |
| Snapshot pruning (pytest) | Verify maxCount and maxAgeHours are respected |
| Config loading (pytest) | Parse valid config, reject invalid, apply defaults |

### Manual / Integration

| Target | What to test |
|---|---|
| REPL adapter | Verify setCode/getCode/evaluate/stop work through the actual `@strudel/repl` web component |
| Failed evaluate safety | Confirm a syntax error does not stop the running scheduler (targeted test from open question) |
| Visual feedback UX | Verify `punchcard`, `spiral`, `pianoroll`, `scope` render correctly and don't block audio |
| Auto Fire validation | Confirm `risk`-level warnings block auto-evaluate |
| Panic flow | Confirm panic stops audio, clears visuals, confirms before reload |

## 12. Current Technical Decisions

Current implementation decisions:

1. **Agent code model**: Agent operates directly on Strudel JS (see §5.1).
2. **Change format**: Full-file replacement with client-side diff (see §5.2).
3. **Agent provider model**: The backend uses direct API provider adapters rather than binding the product workflow to a vendor-specific agent SDK.
4. **Visual layer agent access**: Agent can add/remove/modify visual functions (`punchcard`, `spiral`, etc.) but each visual change generates a `visual` category warning. In `Auto Fire` mode, `risk`-level visual warnings block auto-evaluate.
5. **Browser autosave**: Only on evaluate, not on debounce. The `dirty` flag is informational only; no silent disk writes.
6. **File sync model**: After Phase 2, the SSE file-watch only broadcasts disk changes that originate from outside the browser (e.g., external editor). Agent staging writes directly to the editor via the client bridge, not via file-watch. The `POST /track` endpoint writes editor code to disk on evaluate, which completes the loop.
