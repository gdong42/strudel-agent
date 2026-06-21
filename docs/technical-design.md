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

## 2. Architecture Layers

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

## 3. REPL Adapter Interface

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

## 4. State Machine

### 4.1 Core States

```
activeCode       — last successfully evaluated code (currently performing)
editorCode       — code visible in the REPL editor
lastGoodCode     — most recent known safe fallback
preAgentCode     — editor contents immediately before latest agent stage
changeSet        — metadata for latest agent-staged change
```

### 4.2 State Transitions

| Event | activeCode | editorCode | lastGoodCode | preAgentCode | changeSet |
|---|---|---|---|---|---|
| **Manual evaluate (success)** | ← editorCode | (unchanged) | ← editorCode | (unchanged) | (cleared) |
| **Manual evaluate (failure)** | (unchanged) | (unchanged) | (unchanged) | (unchanged) | (unchanged) |
| **Agent stage** | (unchanged) | ← agent output | (unchanged) | ← previous editorCode | ← agent metadata |
| **Agent undo** | (unchanged) | ← preAgentCode | (unchanged) | (cleared) | (cleared) |
| **Manual edit** | (unchanged) | ← user input | (unchanged) | (unchanged) | (unchanged) |
| **Revert to lastGood** | ← lastGoodCode | ← lastGoodCode | (unchanged) | (cleared) | (cleared) |

### 4.3 Evaluation Rules

1. `Manual Fire` (default): agent stages into editor, user presses Ctrl+Enter to evaluate.
2. `Auto Fire` (opt-in): agent stages into editor AND evaluates immediately after successful validation.
3. Failed evaluation MUST NOT overwrite `lastGoodCode`.
4. Failed evaluation MUST NOT stop the currently running scheduler.
5. `Stop` halts playback and disables Auto Fire.
6. `Panic` stops playback, clears visuals, and presents a confirm dialog before optionally reloading the REPL iframe.

## 5. Agent API Contract

### 5.1 Agent Code Model Decision

**Agent operates directly on Strudel JS**, not on a higher-level song model that compiles to Strudel.

Rationale:
- The editor content is the source of truth; agent must produce valid Strudel JS to be useful.
- A song-model layer adds indirection that makes diff/review harder (user sees compiled code, not intent).
- Advanced users need to inspect and edit agent output directly.
- Revisit the song-model approach only if the agent consistently produces structural errors that a model layer would prevent.

### 5.2 Change Format Decision

**Full-file replacement with a structured diff computed on the client.**

Rationale:
- Full-file is simpler for the agent to generate.
- The client computes the diff for display using the CodeMirror merge extension.
- `preAgentCode` + `editorCode` gives us the before/after pair needed for diff.

### 5.3 Provider Strategy

The product should call model APIs through a narrow provider adapter instead of binding the core workflow to a platform-specific agent SDK.

Rationale:
- We need to support multiple model and API vendors over time.
- The app owns staging, diffing, validation, fire control, snapshots, and recovery.
- Hosted or SDK-specific agent loops can be evaluated inside individual adapters later, but their concepts should not leak into the product state model.
- Direct API calls keep the first implementation easier to reason about and deploy.

Provider adapters should expose the same internal operation:

```python
class AgentProvider(Protocol):
    async def create_change(self, request: ChangeRequest) -> ChangeResponse:
        ...
```

Initial provider examples:

- `OpenAIProvider`: direct OpenAI API call with structured output.
- `AnthropicProvider`: direct Anthropic API call with structured output.
- `MockProvider`: deterministic local provider for tests and UI development.

### 5.4 POST /changes — Request

```python
# POST /changes
class ChangeRequest(BaseModel):
    # User's natural language intent
    intent: str

    # Optional constraints
    scope: str | None = None       # e.g. "drums only", "bass and chords"
    intensity: str | None = None   # e.g. "subtle", "energetic"
    timing: str | None = None      # e.g. "prepare a break", "next section"
    avoid: str | None = None       # e.g. "do not touch bass"

    # Current context
    current_code: str              # editorCode at time of request
    apply_mode: Literal["manual", "auto"]
```

### 5.5 POST /changes — Response

```python
class ChangeResponse(BaseModel):
    # The new full code
    code: str

    # Musical explanation (human-readable, shown in the UI)
    explanation: str

    # Structured warnings
    warnings: list[ChangeWarning] = []

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

### 5.6 Auto Fire Validation

Before auto-evaluating in `Auto Fire` mode, the server validates:
1. Code is non-empty.
2. Mini-notation strings use double quotes or backticks (not single quotes).
3. Known sample names check (from sample registry).
4. No `eval()`, `Function()`, or other dangerous constructs.

If validation fails with warnings at `risk` level, the change is staged but NOT auto-evaluated — the user is prompted.

## 6. Module Responsibilities

### 6.1 Server Modules

| Module | Responsibility |
|---|---|
| `backend/app/main.py` | FastAPI app setup, route registration, SSE management |
| `backend/app/tracks.py` | Track file I/O (read from `tracks/`, write to `tracks/`) |
| `backend/app/snapshots.py` | Snapshot CRUD, pruning (keep last 50 or 24h) |
| `backend/app/changes.py` | `POST /changes`, `GET /changes/latest`, `POST /changes/:id/undo` |
| `backend/app/agent.py` | Prompt construction, provider selection, response parsing, validation |
| `backend/app/providers/` | Vendor-specific direct API adapters behind a stable provider interface |
| `backend/app/samples.py` | Sample registry (list known sample names from `samples/` config) |
| `backend/app/config.py` | Load and watch `project.config.json` |
| `backend/app/models.py` | Pydantic request/response/state models |

### 6.2 Client Modules

| Module | Responsibility |
|---|---|
| `client/repl.ts` | `strudel-editor` adapter (see §3) |
| `client/agent.ts` | Agent panel, prompt input, mode toggle (Manual/Auto Fire) |
| `client/diff.ts` | Diff computation and inline/side-by-side rendering |
| `client/state.ts` | Client-side state machine (§4), transition guards |
| `client/recovery.ts` | Revert to `lastGoodCode`, error display, panic handler |
| `client/status.ts` | Status bar: connection status, last evaluate time, warnings |
| `client/bridge.ts` | SSE listener, HTTP helpers, reconnect logic |
| `client/main.ts` | App bootstrap, glue |

## 7. API Endpoints

```text
GET  /events                     SSE stream (track updates, agent notifications)
POST /track                      Save editor code to disk (from evaluate)
POST /changes                    Stage an agent change
GET  /changes/latest             Get latest staged change metadata
POST /changes/:id/undo           Undo a staged change (restore preAgentCode)
GET  /snapshots                  List snapshots
POST /snapshots/:id/revert       Revert to a snapshot
GET  /samples                    List known samples
```

## 8. File Layout (Revisited)

```text
.
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── agent.py
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

## 9. project.config.json Schema

```json
{
  "trackFile": "tracks/main.strudel.js",
  "snapshots": {
    "maxCount": 50,
    "maxAgeHours": 24
  },
  "agent": {
    "provider": "mock",
    "model": null,
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
