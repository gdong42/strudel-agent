# Testing Strategy

## 1. Overview

Strudel Agent requires several complementary testing layers:

| Layer | Tool | Scope | Confidence |
|---|---|---|---|
| Unit (frontend) | Vitest | State machine, preflight guards, pure functions | High |
| Unit (backend) | pytest | Models, Agent Run transitions, tools, providers, snapshots, track I/O | High |
| Integration (backend) | pytest + httpx TestClient | FastAPI endpoints, SSE | High |
| E2E (mock REPL) | Playwright | Core product flows with a mocked `strudel-editor` API | High |
| Real REPL smoke | Playwright | Minimal checks against the real Strudel REPL | Medium |
| Manual | Human | Audio playback, visual rendering, scheduler behavior | Qualitative |

### Design principle

Test what can be mechanically verified. Reserve human effort for what can't.

Automated tests live alongside code. Mock-REPL E2E tests verify product behavior. Real-REPL E2E tests stay thin and only verify integration smoke. No layer is skipped, no layer is over-invested.

Agent tests must enforce the product boundary: internal candidates, recoverable
validation findings, provider messages, and hidden reasoning never reach the
editor or public run response. Tests should observe state transitions and tool
results, not assert a model's private reasoning.

---

## 2. Unit Tests — Frontend (Vitest)

### 2.1 Why Vitest

- Shares Vite's `vite.config.ts` — zero additional transform config
- Native TypeScript support via esbuild
- `describe`/`it`/`expect` API compatible with Jest
- No jsdom needed for state-machine and pure-function tests

### 2.2 Modules under test

| Module | Why it's unit-testable |
|---|---|
| `src/client/state.ts` — `RuntimeStateStore` | Pure class, data in / data out, no DOM or network |
| `src/client/preflight.ts` — `preflightCode` | Pure function, `string → {errors, warnings}` |
| `src/client/bridge.ts` — fetch wrappers | Mock `globalThis.fetch`, verify request shaping |

### 2.3 Core test cases — `RuntimeStateStore`

| # | Input | Expected |
|---|---|---|
| 1 | Construct with initial payload | `get()` matches initial values |
| 2 | `setEditorCode("x")`, initial `lastGoodCode` is different | `canRevert() → true` |
| 3 | `setEditorCode("x")`, `lastGoodCode` is same | `canRevert() → false` |
| 4 | `markEvaluated(code, snapshot)` | `activeCode`, `editorCode`, `lastGoodCode` all set to `code`; `lastSnapshotId` set |
| 5 | `loadTrack(payload)` | `editorCode` updated from SSE payload |
| 6 | `subscribe(listener)` → `setEditorCode(...)` x2 | Listener called immediately then on each update |
| 7 | `subscribe(listener)` → `unsubscribe()` → `setEditorCode(...)` | Listener NOT called after unsubscribe |
| 8 | `markReverted(snapshot)` | All three code fields set to snapshot code |

### 2.4 Core test cases — `preflightCode`

| # | Input | Expected |
|---|---|---|
| 1 | `""` (empty) | `errors` contains "empty" |
| 2 | `s("bd hh").note("<c4 eb4>")` | `errors == []`, `warnings == []` |
| 3 | `s('bd hh')` (single-quoted pattern) | `warnings` contains "double quotes or backticks" |
| 4 | `s("bd hh")` (double-quoted) | No warnings |
| 5 | `` s(`bd [hh cp]`) `` (backtick) | No warnings |
| 6 | `s("bd").color('cyan')` (single quote in CSS, not mini-notation) | No mini-notation warning |

---

## 3. Unit Tests — Backend (pytest)

### 3.1 Why pytest

- Python standard, no learning curve
- `tmp_path` fixture isolates filesystem state
- Pydantic models are inherently testable (serialize → assert JSON shape → deserialize → assert fields)

### 3.2 Modules under test

| Module | What to test |
|---|---|
| `backend/app/models.py` | Pydantic `alias` serialization (camelCase ↔ snake_case), default values, validation |
| `backend/app/agent_runtime.py` | Run transitions, tool loop, budgets, cancellation, pause/resume, finalization |
| `backend/app/agent_runs.py` | Public projection, resumable state, candidate isolation |
| `backend/app/prompt_contract.py` | Shared instructions and final-change schema |
| `backend/app/tools/` | Tool argument validation, deterministic results, recoverable/fatal errors |
| `backend/app/providers/` | Normalized model turns, tool calls, usage, and vendor error mapping |
| `backend/app/tracks.py` | `read_track` / `write_track` round-trip, missing file behavior |
| `backend/app/snapshots.py` | CRUD, list ordering, prune by count, prune by age |

### 3.3 Core test cases — models

| # | Input | Expected |
|---|---|---|
| 1 | `SnapshotCreateRequest(code="s('bd')")` | `label` defaults to `"Manual evaluate"` |
| 2 | `TrackPayload(...)` → `model_dump(by_alias=True)` | JSON keys are `projectId`, `sessionId`, `code`, `updatedAt` |
| 3 | `RuntimeState(...)` → `model_dump(by_alias=True)` | JSON keys are `projectId`, `sessionId`, `activeCode`, `editorCode`, `lastGoodCode` |

### 3.4 Core test cases — snapshots

| # | Input | Expected |
|---|---|---|
| 1 | `create_snapshot(code, label)` then `read_snapshot(id)` | Returned record matches original |
| 2 | Create A, sleep, Create B, then `list_snapshots()` | B before A (descending by createdAt) |
| 3 | `read_snapshot(nonexistent_id)` | Returns `None` |
| 4 | Create `MAX_SNAPSHOTS + 10`, then `list_snapshots()` | Count capped at `MAX_SNAPSHOTS` |
| 5 | Create old snapshot, advance clock past `MAX_AGE`, `prune()` | Old snapshot removed |

### 3.5 Core test cases — Agent Run

| # | Scenario | Expected |
|---|---|---|
| 1 | Model calls `inspect_diff`, then `validate_candidate`, then `finalize_change` | Tools execute in order chosen by the model; completed final change is returned once |
| 2 | Candidate validation returns a recoverable error | Tool result is appended and another model turn runs; no editor/history change |
| 3 | Model calls `request_user_input` | Run becomes `needs_input`; only the question/options are public |
| 4 | User answers a paused run | Same run resumes with the answer and latest editor version |
| 5 | Editor hash changes before finalization | Stale result is rejected into the loop; editor remains untouched |
| 6 | Turn/time/token budget is exhausted | Run becomes `failed`; no candidate is staged |
| 7 | User cancels during model or tool work | Run becomes `cancelled`; editor/playback/history remain unchanged |
| 8 | Provider/tool returns malformed data | Runtime records a sanitized failure or recoverable tool result without leaking credentials |

---

## 4. Integration Tests — Backend API (pytest + httpx TestClient)

### 4.1 Why FastAPI TestClient

- In-process async transport — no real HTTP server needed
- Full request/response lifecycle through middleware stack
- Most HTTP endpoints can be tested without a real server
- SSE should be tested narrowly because long-lived streams are awkward in in-process clients

### 4.2 Endpoints under test

| Endpoint | Happy path | Error path |
|---|---|---|
| `GET /track` | Returns current track code with metadata | — |
| `POST /track` | Writes code, returns 204, notifies SSE clients | 400 on empty code |
| `GET /state` | Returns RuntimeState with snapshot data | — |
| `GET /snapshots` | Returns sorted list | Empty when no snapshots |
| `POST /snapshots` | Creates snapshot, returns record | 400 on empty code |
| `POST /snapshots/:id/revert` | Reverts track and returns snapshot | 404 on unknown id |
| `POST /agent/runs` | Starts a run and returns public status | 400 on empty intent/code; provider config errors are sanitized |
| `GET /agent/runs/:id` | Returns public run projection | 404 on unknown id; excludes candidates/provider internals |
| `POST /agent/runs/:id/input` | Resumes a `needs_input` run | 409 unless run is waiting for input |
| `POST /agent/runs/:id/editor` | Supplies latest editor version | Rejects invalid/stale sequencing safely |
| `POST /agent/runs/:id/cancel` | Cancels without staging | Idempotent terminal behavior |
| `GET /events` | Initial `track` event and public `agent-run` lifecycle payload | Queue cleanup/reconnect behavior and public-payload boundary covered by E2E/manual smoke |

### 4.3 Shared fixture

```python
# backend/tests/conftest.py
@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    """Redirect track file and snapshot dir to temp paths."""
    track_path = tmp_path / "tracks" / "main.strudel.js"
    track_path.parent.mkdir(parents=True)
    track_path.write_text('s("bd")')

    monkeypatch.setattr("app.tracks.TRACK_PATH", track_path)
    monkeypatch.setattr("app.snapshots.SNAPSHOTS_DIR", tmp_path / "snapshots")
    return {"track_path": track_path, "snapshots_dir": tmp_path / "snapshots"}
```

Longer term, prefer a single `backend/app/paths.py` or `STRUDEL_AGENT_ROOT` setting so tests can redirect the project root without monkeypatching multiple module constants.

---

## 5. E2E Tests — Playwright with Mock REPL

### 5.1 Why Playwright

- Real Chromium engine for app behavior, DOM, network, and event timing
- Mocked `strudel-editor` web component for deterministic tests
- Network interception — assert `POST /track` was (or was not) called
- `expect(locator).toContainText(...)` for status assertions

### 5.2 Scope

Mock-REPL E2E tests verify end-to-end product flows without relying on WebAudio, sample loading, or Strudel internals. They do NOT attempt to assert audio playback or visual rendering quality.

The mock web component should expose the minimum surface used by `src/client/repl.ts`:

```typescript
editor = {
  code,
  setCode(code),
  evaluate(),
  stop(),
  getCursorLocation()
}
```

It should also dispatch the same `update` event expected by the app.

### 5.3 E2E test scenarios

| # | Scenario | Key assertion |
|---|---|---|
| 1 | Load page → Evaluate valid code | Status bar reads "Playing"; `POST /track` and `POST /snapshots` were called after mock `evaluate()` |
| 2 | Mock `evaluate()` throws → Evaluate | Status bar shows error; no `POST /track`; no snapshot; `lastGoodCode` unchanged |
| 3 | Evaluate good code → Modify editor → Revert | Editor restores `lastGoodCode`; revert button becomes disabled |
| 4 | Editor is clean → SSE pushes remote change | Editor updates to remote code |
| 5 | Editor is dirty → SSE pushes remote change | Editor content unchanged; status warns "unsaved changes" |
| 6 | Single-quoted pattern → Evaluate | Warning shown; snapshot still created after successful mock `evaluate()` |
| 7 | Same-code SSE echo after Evaluate | Status remains "Playing" instead of being overwritten by "Loaded" |
| 8 | Panic button | Mock `stop()` called; status shows panic message |
| 9 | Agent internally rejects and revises a candidate | Editor and diff stay unchanged until completed final result arrives |
| 10 | Agent needs clarification | Only the question/options appear; answer resumes the same run |
| 11 | User edits while run is active | Latest editor version reaches the run; stale candidate never overwrites it |
| 12 | Run fails, exhausts budget, or is cancelled | Editor, playback, snapshot, and change history remain unchanged |
| 13 | Completed Manual Fire run | One final change is staged with final diff/explanation; no evaluate call |
| 14 | Completed Auto Fire run passes gates | Final change evaluates once; failed gates return to the agent or block completion |

### 5.4 Real REPL smoke tests

Real Strudel REPL tests should be a separate thin suite:

| # | Scenario | Key assertion |
|---|---|---|
| 1 | Load page with real `@strudel/repl` | `strudel-editor.editor` eventually exists |
| 2 | Evaluate a minimal valid pattern | No application-level fatal error is shown |
| 3 | Stop | No application-level fatal error is shown |

These tests may run in CI if stable enough, but they should not carry core correctness coverage.

### 5.5 E2E limitations

These are **excluded from automated E2E** and must be verified manually:

| Limitation | Why | Mitigation |
|---|---|---|
| Audio is actually playing | No JS API to inspect WebAudio output | Smoke-test manual check per release |
| Visuals cleared on panic | Canvas/WebGL state not inspectable | Manual check |
| Scheduler audio actually continues after failed evaluate | Requires auditory or WebAudio-level inspection | Mock E2E verifies no save/snapshot/last-good overwrite; manual test verifies audible behavior |
| Frame rate under visual load | Needs profiler, not assertion | Browser Performance API logging (Phase 5 task P5.5) |

---

## 6. File Layout

```text
strudel/
├── backend/
│   ├── app/
│   │   └── ... (unchanged)
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py              # Shared fixtures
│       ├── test_models.py
│       ├── test_agent_runtime.py
│       ├── test_agent_runs.py
│       ├── test_tools.py
│       ├── test_providers.py
│       ├── test_prompt_contract.py
│       ├── test_tracks.py
│       ├── test_snapshots.py
│       └── test_api.py
├── src/
│   └── client/
│       └── ... (unchanged)
├── test/
│   └── client/
│       ├── state.test.ts
│       ├── preflight.test.ts
│       └── bridge.test.ts
├── e2e/
│   ├── playwright.config.ts
│   ├── mock-repl.spec.ts
│   └── real-repl.smoke.spec.ts
├── vitest.config.ts
├── package.json
└── TODO.md
```

---

## 7. Run Commands

```bash
# Frontend unit tests
npx vitest run

# Frontend unit tests in watch mode
npx vitest

# Backend unit + integration tests
cd backend && uv run pytest

# E2E tests (can auto-start dev servers through Playwright webServer)
# Terminal 3: npx playwright test
```

### package.json scripts (to add)

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "test:e2e:mock": "playwright test e2e/mock-repl.spec.ts",
    "test:e2e:real": "playwright test e2e/real-repl.smoke.spec.ts"
  }
}
```

### backend/pyproject.toml (to add)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[project.optional-dependencies]
test = ["pytest>=8", "pytest-asyncio", "httpx"]
```

---

## 8. CI Matrix

```text
pull_request:
  - unit-frontend  (vitest run)
  - unit-backend   (pytest)
  - e2e-mock       (playwright mock REPL, dev server + backend started as fixtures)
  - e2e-real-smoke (optional/manual gate until stable)
```

E2E in CI requires:
- `playwright install chromium --with-deps` in the CI image
- Both Vite dev server and Python backend started before Playwright runs
- Dev server on `127.0.0.1:5173`, backend on `127.0.0.1:8787`

Playwright can be configured to handle this with `webServer`:

```typescript
// e2e/playwright.config.ts
export default defineConfig({
  webServer: [
    { command: 'npm run dev -- --port 5173', port: 5173 },
    { command: 'cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8787', port: 8787 },
  ],
});
```

---

## 9. What Is NOT Automated

| Category | Why not automated | Verification cadence |
|---|---|---|
| Audio output correctness | No WebAudio introspection | Per-release manual smoke |
| Visual rendering (scope, pianoroll, spiral) | Canvas/WebGL state opaque to tests | Per Strudel version bump |
| Scheduler resilience (failed evaluate doesn't stop playback) | Requires human auditory perception | Targeted test per T2.8 |
| Frame rate / performance | Needs profiler + visual judgment | Phase 5 instrumentation |
| Musical quality and taste | Deterministic assertions cannot judge groove or mood | Fixed scenario review during agent evaluation/tuning |
| Cross-browser compatibility | Strudel targets Chromium-family | N/A — not a goal |
