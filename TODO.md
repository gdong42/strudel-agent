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

- [ ] **P3.1** Implement `POST /changes` endpoint (`backend/app/changes.py`)
- [ ] **P3.2** Implement `GET /changes/latest` and `POST /changes/:id/undo`
- [ ] **P3.3** Implement `src/client/agent.ts` panel (prompt input, scope/intensity controls)
- [ ] **P3.4** Wire agent stage flow: request → response → setCode in editor → show diff → wait
- [ ] **P3.5** Store `preAgentCode` and `changeSet` on stage; wire undo to revert
- [ ] **P3.6** Show musical explanation and warnings in the diff panel
- [ ] **P3.7** Implement Manual Fire / Auto Fire toggle
- [ ] **P3.8** In Auto Fire: validate response, auto-evaluate on success, block on risk warnings
- [ ] **P3.9** Implement `src/client/diff.ts` (full-file diff computation + inline render)

## Phase 4: Agent Integration and Prompt Contract

- [ ] **P4.1** Implement `backend/app/agent.py` prompt construction and provider selection
- [ ] **P4.2** Implement provider adapter interface in `backend/app/providers/base.py`
- [ ] **P4.3** Add mock provider for deterministic UI/backend development
- [ ] **P4.4** Add first direct API provider adapter (OpenAI or Anthropic)
- [ ] **P4.5** Wire `agent-context.md` into the system prompt on each request
- [ ] **P4.6** Add project convention fields (mood, stems, arrangement markers) to config
- [ ] **P4.7** Store agent prompts and responses in `changes/` directory
- [ ] **P4.8** Add scope constraint parsing ("only drums", "don't touch bass")
- [ ] **P4.9** Add intensity constraint parsing ("subtle", "energetic", "10% more")
- [ ] **P4.10** Add timing constraint parsing ("prepare a break", "make a drop")
- [ ] **P4.11** Tune prompt format based on real usage quality

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
