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

- [x] **P3.1** Implement `POST /changes` endpoint (`backend/app/changes.py`)
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
- [x] **P4A.4** Route `POST /changes` through agent service before persistence
- [x] **P4A.5** Test provider mapping, invalid responses, selection, and API failure behavior

### Phase 4B.1: Provider Settings

- [x] **P4B1.1** Add a settings dialog for provider, model, and API key
- [x] **P4B1.2** Use backend config as defaults and browser settings as overrides
- [x] **P4B1.3** Store API keys in session or persistent browser storage by user choice
- [x] **P4B1.4** Pass credentials to the backend per request without server persistence
- [x] **P4B1.5** Add provider discovery, connection test, and settings tests
- [x] **P4B1.6** Remove premature scope, intensity, timing, and avoid product fields

### Phase 4B.2: First Real Provider

- [x] **P4B2.1** Select the first provider and default model
- [x] **P4B2.2** Implement its direct API adapter with structured output
- [x] **P4B2.3** Add timeout, cancellation, and user-facing provider errors
- [x] **P4B2.4** Add loading, cancellation, and duplicate-submit behavior to the agent panel
- [x] **P4B2.5** Record provider, model, and latency without persisting credentials
- [x] **P4B2.6** Add DeepSeek Chat Completions support and use `deepseek-v4-pro` by default

### Phase 4B.3: Concurrent Editing

- [ ] **P4B3.1** Capture request base code and hash
- [ ] **P4B3.2** Detect editor changes while a provider request is running
- [ ] **P4B3.3** Keep stale responses outside the editor as candidates
- [ ] **P4B3.4** Add Regenerate, Use agent code, and Dismiss actions

### Phase 4C: Prompt Contract

- [ ] **P4C.1** Define the system prompt and structured response schema
- [ ] **P4C.2** Interpret constraints from the user's freeform musical intent
- [ ] **P4C.3** Add post-generation checks for obvious scope violations
- [ ] **P4C.4** Add a minimal fixed prompt test set

### Phase 4D: Project Context

- [ ] **P4D.1** Define the minimal `agent-context.md` format
- [ ] **P4D.2** Load and inject project context with size and error handling
- [ ] **P4D.3** Keep musical conventions in context and machine settings in config

### Phase 4E: Conversation and Revision

- [ ] **P4E.1** Define session conversation state and retention boundaries
- [ ] **P4E.2** Include recent requests, explanations, and outcomes in revisions
- [ ] **P4E.3** Persist change audit data without storing secrets

### Phase 4F: Evaluation and Prompt Tuning

- [ ] **P4F.1** Build fixed musical capability scenarios
- [ ] **P4F.2** Record syntax validity, constraint adherence, and musical review results
- [ ] **P4F.3** Tune prompts against the evaluation set

## Phase 5: Validation and Performance Hardening

- [ ] **P5.1** Implement `backend/app/samples.py`; warn on unknown samples in agent output
- [ ] **P5.2** Visual change detection: flag any visual function modifications
- [ ] **P5.3** Auto Fire safety: block auto-evaluate on structural or visual risk warnings
- [ ] **P5.4** Add visual disable toggle (for low-power or audio-critical performance)
- [ ] **P5.5** Browser performance logging for visual draw load (fps, frame time)
- [ ] **P5.6** Panic flow: confirm dialog → stop audio → clear visuals → optional REPL reload
- [ ] **P5.7** Add agent capability tests from spec: "only change drums" / "increase energy 10%" / "prepare break, don't evaluate"
- [ ] **P5.8** Write automated tests for state machine transitions (§4.2)
- [ ] **P5.9** Write automated tests for agent response validation and preflight guards

---

## Task Dependency Notes

- Phase 2 depends on Phase 1 (no Pydantic models or client state machine without the shell)
- Phase 3 depends on Phase 2 (needs state model, config, and recovery behavior)
- Phase 4 depends on Phase 3 (needs staging flow before tuning prompt)
- Phase 5 depends on Phase 4 (needs agent producing real output before hardening)
