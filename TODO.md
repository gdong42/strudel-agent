# TODO

## Phase 1: REPL Runtime Shell

- [x] **P1.1** Scaffold frontend Vite + TypeScript project (`package.json`, `tsconfig.json`, `vite.config.ts`)
- [x] **P1.2** Pin `@strudel/repl@1.3.0` and create minimal `index.html` entry
- [x] **P1.3** Implement `src/client/repl.ts` adapter (getCode, setCode, evaluate, stop, onUpdate)
- [x] **P1.4** Scaffold Python FastAPI backend (`backend/pyproject.toml`, `backend/app/main.py`)
- [x] **P1.5** Implement `backend/app/tracks.py` (read/write `tracks/main.strudel.js`)
- [x] **P1.6** Add Evaluate, Stop, Panic buttons in the UI
- [x] **P1.7** Implement `src/client/status.ts` (connection status, last evaluate time, errors)
- [x] **P1.8** Implement `src/client/bridge.ts` (SSE listener, POST `/track` helper)
- [x] **P1.9** Implement `src/client/main.ts` (bootstrap, wire UI to adapter and bridge)
- [x] **P1.10** Migrate POC `track.strudel.js` content to `tracks/main.strudel.js`

## Phase 2: State, History, and Recovery

- [x] **P2.1** Define local-first `backend/app/models.py` with project/session, track, and snapshot API models
- [x] **P2.2** Implement `src/client/state.ts` state machine (projectId, sessionId, activeCode, editorCode, lastGoodCode)
- [x] **P2.3** Implement `backend/app/snapshots.py` (create on successful evaluate, list, revert, pruning: max 50 or 24h)
- [x] **P2.4** Implement `src/client/recovery.ts` (revert-to-lastGood button, snapshot revert, error display)
- [x] **P2.5** Add dirty-editor detection (expose `isDirty` from adapter, warn on agent stage if dirty)
- [x] **P2.6** Remove POC auto-overwrite behavior from SSE track events (agent staging uses separate channel)
- [x] **P2.7** Add preflight guards: empty code check, single-quote mini-notation warning
- [x] **P2.8** Targeted test: verify failed `editor.evaluate()` does not overwrite `lastGoodCode`
- [x] **P2.9** Implement `backend/app/config.py` (load `project.config.json`, apply defaults)
- [x] **P2.10** Add snapshot list UI and one-click revert to any snapshot

## Phase 3: Agent Staging and Diff

- [x] **P3.1** Implement staged-change persistence in `backend/app/changes.py`
- [x] **P3.2** Implement `GET /changes/latest` and `POST /changes/:id/undo`
- [x] **P3.3** Implement `src/client/agent.ts` panel (prompt input and apply controls)
- [x] **P3.4** Wire agent stage flow: request → response → setCode in editor → show diff → wait
- [x] **P3.5** Store `preAgentCode` and `changeSet` on stage; wire undo to revert
- [x] **P3.6** Show musical explanation and warnings in the diff panel
- [x] **P3.7** Implement Manual Fire / Auto Fire toggle
- [x] **P3.8** In Auto Fire: validate response, auto-evaluate on success, block on risk warnings
- [x] **P3.9** Implement `src/client/diff.ts` (full-file diff computation + inline render)

## Phase 4: Agent Integration and Prompt Contract

### Phase 4A: Provider Contract

- [x] **P4A.1** Define the async provider request/response contract and provider error type
- [x] **P4A.2** Add agent service provider selection and response validation
- [x] **P4A.3** Move deterministic generation into `MockProvider`
- [x] **P4A.4** Route agent generation through provider selection before staging
- [x] **P4A.5** Test provider mapping, invalid responses, selection, and API failure behavior

### Phase 4B.1: Provider Settings

- [x] **P4B1.1** Add a settings dialog for provider, model, and API key
- [x] **P4B1.2** Use backend config as defaults and browser settings as overrides
- [x] **P4B1.3** Store API keys in session or persistent browser storage by user choice
- [x] **P4B1.4** Pass credentials to the backend per request without server persistence
- [x] **P4B1.5** Add provider discovery, connection test, and settings tests
- [x] **P4B1.6** Remove premature scope, intensity, timing, and avoid product fields
- [x] **P4B1.7** Add per-provider/model runtime profiles, optional cumulative token limits, and Run-start snapshots

### Phase 4B.2: First Real Provider

- [x] **P4B2.1** Select the first provider and default model
- [x] **P4B2.2** Implement its direct API adapter with structured output
- [x] **P4B2.3** Add timeout, cancellation, and user-facing provider errors
- [x] **P4B2.4** Add loading, cancellation, and duplicate-submit behavior to the agent panel
- [x] **P4B2.5** Record provider, model, and latency without persisting credentials
- [x] **P4B2.6** Add DeepSeek Chat Completions support and use `deepseek-v4-flash` by default

### Phase 4B.3: Concurrent Editing and Automatic Reconciliation (Transitional)

- [x] **P4B3.1** Capture each request's base code and SHA-256 hash
- [x] **P4B3.2** Detect editor changes while a provider request is running
- [x] **P4B3.3** Run up to two automatic reconciliation turns against the latest stable editor code
- [x] **P4B3.4** Keep reconciled results staged and block Auto Fire after concurrent user edits
- [x] **P4B3.5** Test reconciliation input, no-op responses, and browser behavior

The current bounded client-side reconciliation protects user edits while the
provider is still one-shot. P4C migrates this behavior into the Agent Run so
concurrent editor updates become new run context rather than a separate product
workflow.

### Phase 4C: Agent Runtime and Tool Loop

- [x] **P4C.1** Define shared agent instructions and the structured final-change schema
- [x] **P4C.2** Define `AgentRun`, model-turn, tool-call, final-result, and failure contracts
- [x] **P4C.3** Refactor providers from one-shot `create_change` into vendor-neutral model turns with normalized tool calls
- [x] **P4C.4** Implement the tool registry with `inspect_diff`, `validate_candidate`, `finalize_change`, and `request_user_input`
- [x] **P4C.5.1** Add validated Run construction, immutable transitions, and a scripted model-turn test provider
- [x] **P4C.5.2** Execute one model turn, run ordered tool calls, and return serialized tool results to the model
- [x] **P4C.5.3** Handle `finalize_change`, `request_user_input`, invalid plain-text/terminal tool outcomes, and deterministic finalization gates
- [x] **P4C.5.4.1** Enforce turn, time, and token budgets; sanitize terminal provider and runtime failures
- [x] **P4C.5.4.2** Define cancellable active-turn execution; attach it to background-task ownership next
- [x] **P4C.6.1a** Add an in-memory Run manager, worker loop, task ownership, and active-task credential confinement
- [x] **P4C.6.2** Add start/read Run endpoints and public lifecycle events
- [x] **P4C.6.3** Add input, editor-update, and cancel commands for active Runs
- [x] **P4C.7.1** Replace the client generation path with Run status handling and final-only Manual Fire staging
- [x] **P4C.7.2** Add an editor-hash stage acknowledgement that persists a change only after the final Run is accepted
- [x] **P4C.7.3** Enable Auto Fire only after accepted staging and deterministic finalization gates
- [x] **P4C.8.1** Stream debounced editor versions to active Runs with ordered base-hash sequencing
- [x] **P4C.8.2** Keep a final stale until its latest editor update is reconciled; never overwrite a newer browser edit
- [x] **P4C.8.3** Retire the legacy one-shot change generation path and fixed reconciliation contracts after Run migration coverage
- [x] **P4C.9.1** Cover cancellation, stale finals, and final-only staging in Mock-REPL E2E
- [x] **P4C.9.2** Cover failed terminal Runs in Mock-REPL E2E without editor, playback, or history mutation
- [x] **P4C.10.1** Stream bounded browser-safe model-turn and tool activity and restore it after reconnect
- [x] **P4C.10.2** Render elapsed time, turn state, and tool activity in the Agent panel
- [x] **P4C.10.3** Add provider token streaming for explicitly public assistant commentary without exposing raw provider output

### Phase 4D: Human-in-the-Loop Clarification

- [x] **P4D.1** Add `needs_input` question/option UI without exposing internal candidates or validation findings
- [x] **P4D.2** Resume the same Agent Run with the user's answer and latest editor version
- [x] **P4D.3.1** Restore an active public Run after browser reload without persisting credentials
- [x] **P4D.3.2** Refresh the active Run after SSE reconnect and cover pause, answer, cancel, and resume behavior

### Phase 4E: Project Context

- [x] **P4E.1** Define the minimal `agent-context.md` format
- [x] **P4E.2** Load project context into each Agent Run with size and error handling
- [x] **P4E.3** Keep musical conventions in context and machine settings in config

### Phase 4F: Conversation and Revision

- [x] **P4F.1** Define session conversation state and retention boundaries
- [x] **P4F.2** Include recent requests, user clarifications, final explanations, and outcomes in revisions
- [x] **P4F.3** Persist run/change audit data without credentials, hidden reasoning, or discarded candidate code

### Phase 4G: Evaluation and Agent Tuning

- [x] **P4G.1** Build a baseline set of fixed musical capability scenarios immediately after the Run migration
- [x] **P4G.2.1** Define an evaluation assessment contract and deterministic final/region checks
- [x] **P4G.2.2** Execute a scenario through an Agent Run and capture terminal, loop, and tool observations
- [x] **P4G.2.3** Add structured human musical review and aggregate evaluation reports
- [ ] **P4G.3.1** Add an opt-in Provider baseline runner that accepts a one-time environment key and emits safe reports
- [ ] **P4G.3.2** Run the selected Provider, complete human reviews, and tune instructions, tools, and budgets from measured results
- [ ] **P4G.3.3** Compact repeated candidate and tool history when measured token growth justifies it

## Phase 5: Validation and Performance Hardening

- [x] **P5.1.1** Define a versioned local sample registry and project-confined loader
- [x] **P5.1.2** Expose declared samples through a deterministic Agent lookup/validation tool
- [x] **P5.1.3** Surface declared samples through the local API and workspace UI
- [ ] **P5.2** Upgrade heuristic candidate checks with available Strudel syntax and mini-notation validation
- [ ] **P5.3** Add richer visual and structural diff inspection tools for the agent's self-review
- [ ] **P5.6** Add visual disable toggle and browser performance logging for audio-critical performance
- [ ] **P5.7** Panic flow: confirm dialog → stop audio → clear visuals → optional REPL reload
- [ ] **P5.8** Extend capability tests with "only change drums", "increase energy 10%", and conflicting-constraint scenarios
- [ ] **P5.9** Extend finalization, validation, and performance regression coverage beyond the Phase 4 Run migration suite

---

## Task Dependency Notes

- Phase 2 depends on Phase 1 (no Pydantic models or client state machine without the shell)
- Phase 3 depends on Phase 2 (needs state model, config, and recovery behavior)
- Phase 4 depends on Phase 3 (the runtime needs a safe final staging boundary)
- Phase 4D depends on the resumable Run API from Phase 4C
- Phase 4E–4G depend on Agent Run state and tool execution from Phase 4C
- Phase 5 extends Phase 4C validation and finalization; it does not introduce a separate user review flow
