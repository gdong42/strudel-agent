# Live Vibe Coding Development Plan

## Purpose

Build a Strudel agent for creating and performing live-coded music through natural language, direct code editing, or a combination of both.

The long-term product goal is not merely "Strudel plus an assistant." The goal is an agentic music-making environment where a user can describe musical intent directly, hear and see the result, iterate conversationally, and optionally ignore the underlying code entirely. In that mature form, natural language can be the primary interaction model.

At the same time, Strudel code remains a first-class representation of the music:

- It is the executable source of truth for Strudel's runtime.
- It gives advanced users and performers a precise way to inspect, edit, and take over.
- It makes agent actions reviewable, diffable, versionable, and reversible.
- It provides a safety boundary for live performance: generated changes can be staged before they affect the running set.

The first formal version should therefore preserve the official Strudel REPL as the visible performance surface while adding the agent as a powerful parallel interaction path. Over time, the product may shift toward an agent-first interface, where the code editor becomes optional, collapsible, or primarily used for inspection and manual override.

## Product Principles

- Agent-first, code-capable: the user should be able to create music through natural language, but code should remain available for precision, learning, inspection, and takeover.
- Performance-safe by default: generated changes should not unexpectedly disrupt a live set.
- Reversible at every step: the user should be able to recover the last good musical state quickly.
- Transparent when needed: the agent should expose what it changed, why it changed it, and what musical effect it expects.
- Agent-owned quality: the agent should inspect and repair recoverable problems internally instead of delegating its intermediate mistakes to the user.
- Purposeful human input: pause for the user only when intent is materially ambiguous, constraints conflict, or a key creative decision belongs to the performer.
- Progressive disclosure: beginners can stay in natural language and high-level controls; experienced Strudel users can work directly in the editor.
- Local-first for performance: the live runtime should not depend on network availability once required packages and samples are available.

## Delivery Model

The first formal product should be a local-first workspace tool, not a hosted cloud service. A user runs the app on their own machine, and the backend serves the local browser session, local track files, snapshots, changes, samples, and project config.

This keeps the live runtime predictable for performance and avoids prematurely introducing accounts, cloud storage, permissions, hosted API-key custody, billing, and abuse controls before the agent workflow is proven.

The data model should still be compatible with a future hosted product:

- A `project` is a local workspace directory in the first version.
- A `session` is the current browser/backend runtime state for that workspace.
- `project_id` and `session_id` can exist as local identifiers now, without implying a user account.
- Tracks, snapshots, changes, and agent metadata should be stored through explicit project/session APIs rather than hidden global state.

If the product later moves toward a strudel.cc-style hosted experience, the same concepts can map to database-backed users, projects, sessions, assets, and shareable performances.

## Target Experience

The mature experience should support several modes without treating them as separate products:

- Conversational creation: the user describes intent, such as "make this more hypnotic and reduce low-end mud," and the agent updates the music.
- Live performance control: the user can ask for prepared changes, review them, and fire them at the right moment.
- Manual live coding: the user can edit Strudel code directly, use normal REPL shortcuts, and ignore the agent when desired.
- Learning and explanation: the user can ask what a pattern does, why a change works, or how to manually recreate it.
- Agent-led exploration: the agent can suggest variations, transitions, visual treatments, or arrangement ideas within user-defined constraints.

For the first formal version, the editor remains visible because it is the most reliable way to inspect and control what the agent is doing. This is an implementation and trust-building choice, not a limitation of the final product direction.

## Interaction Design

### Agent Interaction

The user can interact with the agent through musical intent rather than code. The agent can propose and revise changes to rhythm, harmony, arrangement, samples, effects, and visuals.

Users can express constraints directly in natural language:

- scope: "only change drums", "do not touch bass", "visuals only"
- intensity: "subtle", "more energetic", "make it peak"
- timing: "prepare a break", "make a drop for the next section"
- protection: "keep the current groove", "do not add low-end"

The early product does not expose these as separate scope, intensity, timing, or
protection fields. They remain part of the freeform request until usage shows that
a stable structured control would improve the interaction.

The agent should explain its final changes in musical terms, not only code
terms. Internal candidates, self-review, recoverable validation failures, and
revision attempts are agent working state and should not become user-facing
review tasks.

Long-running work should still feel live. While a Run is active, the interface
shows elapsed time, the current model turn, and normalized activity such as an
allowlisted tool name. This timeline is progress feedback, not a transcript or
an approval queue. It may stream short assistant commentary explicitly written
for the user, while candidate code, arbitrary model output, tool payloads, and
hidden reasoning remain private until the agent produces a final result or asks
a material clarification.

### Agent Apply Mode

The product should expose only two agent apply modes:

- `Manual Fire`: the agent stages a completed final change directly into the editor, shows a diff or change summary, and waits. The user decides when to evaluate with `Ctrl+Enter` or `Evaluate`. This is the default mode.
- `Auto Fire`: the agent stages and evaluates a completed final change automatically after deterministic finalization gates pass. This is opt-in and intended for exploration, rehearsal, or low-risk situations.

`Manual Fire` deliberately has no separate "accept" step. The agent's response becomes an editable staged change in the REPL immediately, but it does not affect the running music until the user fires it. The user can review the diff, undo the staged change, keep editing, or ask the agent to revise.

### Agent Staging Flow

When the user gives a natural language prompt in `Manual Fire` mode:

1. Start an Agent Run with the current editor version, musical context, and user intent.
2. The agent generates candidates, uses available tools to inspect diffs and validate them, and revises recoverable problems internally while the UI shows normalized progress.
3. If a material ambiguity, constraint conflict, or key creative decision remains, pause the run and ask one concise question. Resume the same run after the answer.
4. When the agent has a finalized result, stage only that result in the editor.
5. Show the final diff, musical explanation, and only irreducible risks or unverifiable limitations.
6. The user can fire it, undo it, manually edit it, or ask the agent for a new revision.

The app does not expose ordinary intermediate candidates or ask the user to
decide whether the agent violated its own interpretation of the request. For
example, if "only change drums" produces a candidate that also changes bass,
the agent should see that in its diff/tool results and continue correcting it.

This separates "stage this edit" from "perform this edit." That distinction is important during live coding because a performer may want the agent to prepare code immediately, adjust a parameter manually, and fire it on a phrase boundary.

### Manual Code Interaction

The REPL remains directly editable. The user can inspect, modify, reject, or fully replace agent-generated code at any time.

When the user presses `Ctrl+Enter` or clicks `Evaluate`:

1. Save the visible track.
2. Try to run it through the official Strudel REPL.
3. If evaluation succeeds, mark this version as the current performing version and latest safe fallback.
4. If evaluation fails, keep the last running performance state where possible and show the error clearly.

### Error Handling

Errors should be non-destructive.

The app and agent tools should handle at least:

- JavaScript syntax errors.
- Strudel mini-notation parse errors.
- Unknown sample names.
- Failed sample loading.
- Visual feedback errors.
- Runtime audio errors.
- Server disconnects.

Recoverable candidate errors are returned to the Agent Run as tool results so
the agent can revise. Only terminal runtime/product errors cross the user-facing
boundary. On a terminal error:

- Show the error in a visible status panel.
- Keep the editor code intact.
- Do not overwrite the latest safe fallback.
- Offer one-click revert to the latest safe fallback.
- Avoid clearing or stopping audio unless the user explicitly hits Stop/Panic.

## Proposed Architecture

```text
Browser
  ├─ Strudel REPL adapter
  ├─ agent conversation panel
  ├─ staged change / diff panel
  ├─ Manual Fire / Auto Fire controls
  ├─ status/error/recovery panel
  ├─ version timeline
  └─ client event bridge

Local server
  ├─ project/session state
  ├─ track file API
  ├─ Agent Run API and event stream
  ├─ Agent Runtime / tool loop
  ├─ tool registry
  ├─ model-turn provider adapters
  ├─ snapshot/change history store
  ├─ sample/config registry
  └─ browser event stream

Workspace
  ├─ tracks/
  ├─ snapshots/
  ├─ changes/
  ├─ samples/
  ├─ project.config.json
  └─ agent-context.md
```

The architecture has three core responsibilities:

- Agent layer: own the model/tool loop, inspect and repair candidates, pause for essential user decisions, and emit one finalized musical change.
- Runtime layer: keep the official Strudel REPL as the executable music surface for the first formal version.
- Recovery layer: preserve history, snapshots, staged changes, and the latest safe fallback so live performance remains reversible.

The model/API provider is replaceable. OpenAI, Anthropic, local models, or other API providers can back the agent service, but the agent workflow itself is a core product capability rather than an optional bridge.

## State And Performance Safety Model

Safety here means live performance safety: preserving the running set, avoiding surprise evaluation, and keeping recovery paths available. The app should keep several explicit states so visible editor contents and running performance state do not collapse into one unsafe value:

- `activeCode`: the last code that successfully evaluated and is currently allowed to be performing.
- `editorCode`: the code currently visible and editable in the REPL.
- `lastGoodCode`: the most recent known safe fallback.
- `preAgentEditorCode`: the editor contents immediately before the latest agent-staged change, used for diff and undo.
- `changeSet`: metadata for the latest agent-staged change, including explanation, warnings, and changed ranges.
- `agentRun`: separate backend working state for model turns, tool results, budgets, optional clarification, and a final result.

This separation supports both product directions:

- In agent-first flows, generated work can appear immediately in the editor without becoming active.
- In manual live coding flows, the user can directly edit and evaluate without waiting for the agent.
- In `Manual Fire`, generated changes can be staged without disrupting the running set.
- Internal Agent Run candidates do not become `editorCode` or `changeSet`.

Sync rules:

- The visible editor is the source of truth while a browser session is active.
- Only a completed Agent Run stages code into the editor in `Manual Fire`; internal candidates never do.
- Staging a change records `preAgentEditorCode` and `changeSet` so the user can inspect or undo it.
- Browser edits are saved to disk on evaluate.
- If the editor changes during a run, supply the new version to that run and require another reconciliation/self-review turn.
- Before staging, compare editor hashes again; stale final results return to the run and never overwrite the editor.

Evaluation rules:

- `Manual Fire` requires human action with `Ctrl+Enter` or `Evaluate`.
- `Auto Fire` can stage and evaluate only a completed result that passed deterministic finalization gates.
- `Stop` stops playback and disarms automatic evaluation.
- `Panic` should stop playback, clear visuals, and optionally reload the REPL frame.
- Successful evaluation records a snapshot and updates `lastGoodCode`.
- Failed evaluation must not overwrite `lastGoodCode`.

The Agent Run owns candidate generation, validation, reconciliation, and
revision behind the finalization boundary. Evaluation remains a user action
unless `Auto Fire` is explicitly enabled and the completed result passes all
gates.

## Runtime Choice

Use `@strudel/repl` as the primary runtime and editor for the first formal version.

Rationale:

- It preserves the official Strudel editing experience.
- It keeps CodeMirror, mini-notation transpilation, highlighting, draw context, scheduler, and WebAudio wiring inside Strudel's maintained package.
- It lets the performer use normal Strudel keyboard habits.
- It avoids rebuilding `strudel.cc` from lower-level packages before the product interaction is proven.

We should still keep the integration thin and version-pinned:

```html
<script src="https://unpkg.com/@strudel/repl@1.3.0"></script>
```

Longer term, move from CDN to pinned npm dependencies with a Vite/TypeScript build.

## POC Validation Notes

The POC validated the main integration direction:

- `@strudel/repl@1.3.0` can be embedded with `<strudel-editor>`.
- The web component exposes `repl.editor`, including `setCode`, `evaluate`, `stop`, cursor helpers, and CodeMirror-backed editing.
- File changes can be pushed to the browser with Server-Sent Events.
- Browser edits can be written back to disk through a local HTTP endpoint.
- Strudel REPL mini-notation expects double quotes or backticks. Single-quoted pattern strings are treated as plain JavaScript strings and will not be mini-notation-transpiled.
- Non-pattern string values, such as CSS colors in visual config objects, should use single quotes to avoid being scanned as mini-notation.
- Visual feedback functions such as `punchcard`, `spiral`, `pianoroll`, and `scope` can be used through the embedded REPL. Their UX and performance characteristics need dedicated testing in the formal app.

## Data and File Layout

Initial formal project layout:

```text
.
├─ backend/
│  ├─ pyproject.toml
│  └─ app/
│     ├─ main.py
│     ├─ agent_runtime.py
│     ├─ agent_runs.py
│     ├─ session_conversation.py
│     ├─ run_audit.py
│     ├─ prompt_contract.py
│     ├─ changes.py
│     ├─ tracks.py
│     ├─ snapshots.py
│     ├─ samples.py
│     ├─ config.py
│     ├─ models.py
│     ├─ tools/
│     └─ providers/
├─ src/
│  └─ client/
│     ├─ agent.ts
│     ├─ bridge.ts
│     ├─ diff.ts
│     ├─ main.ts
│     ├─ repl.ts
│     ├─ recovery.ts
│     └─ status.ts
├─ tracks/
│  └─ main.strudel.js
├─ snapshots/
├─ changes/
├─ audits/
├─ samples/
├─ project.config.json
├─ agent-context.md
├─ evals/
├─ docs/
├─ package.json
├─ tsconfig.json
└─ vite.config.ts
```

The current single-file POC can stay as a reference, but formal development should move to a Python FastAPI backend, TypeScript/Vite frontend, and explicit modules.

## Development Plan

### Phase 1: REPL Runtime Shell

- Replace the current static POC with a Vite/TypeScript app.
- Pin `@strudel/repl`.
- Wrap `strudel-editor` in a small adapter:
  - `getCode()`
  - `setCode(code)`
  - `evaluate()`
  - `stop()`
  - `onUpdate(state)`
- Add visible status and error panels.
- Add Stop and Panic controls.

### Phase 2: State, History, and Recovery

- Move track code to `tracks/main.strudel.js`.
- Save editor code on evaluate.
- Add snapshots for every successful evaluation.
- Add one-click revert to `lastGoodCode`.
- Add dirty-editor detection.
- Stop auto-overwriting the editor from external file changes.
- Add preflight guards for empty code and obvious mini-notation quote mistakes.
- Verify whether failed `editor.evaluate()` can interrupt the currently running scheduler.

### Phase 3: Agent Staging and Diff

- Add change-history endpoints:
  - `GET /changes/latest`
  - `POST /changes/:id/undo`
- Stage completed Agent Run finals through `POST /agent/runs/:id/stage`.
- Show side-by-side or inline diff.
- Agent changes update the editor but do not evaluate in `Manual Fire`.
- Staged changes remain in history for review and recovery.
- Show musical explanation and warnings for each staged change.

### Phase 4: Agent Runtime and Context

- Replace one-shot generation with a vendor-neutral model-turn and tool-call contract.
- Add a bounded Agent Run loop with tool execution, cancellation, finalization, and public run states.
- Stream a bounded browser-safe activity timeline with model-turn progress,
  elapsed time, and allowlisted tool names; restore it after reconnect.
- Stream throttled public commentary from provider content channels while
  excluding reasoning events, tool arguments, and raw provider payloads.
- Keep candidates and recoverable findings internal; persist and stage only completed final changes.
- Add `needs_input` pause/resume for material ambiguity, conflicting constraints, and key creative decisions.
- Feed concurrent editor updates into the active run so the agent reconciles and self-reviews again.
- Add optional project context from `agent-context.md`; keep musical conventions
  there and retain runtime defaults in `project.config.json`.
- Add a bounded, process-local session conversation ledger for revisions; keep
  it separate from durable audit metadata and never store credentials, hidden
  reasoning, or discarded candidate code.
- Maintain fixed musical scenarios to tune instructions, tools, and runtime budgets.

### Phase 5: Validation Tools and Performance Hardening

- Add sample, syntax, mini-notation, structural, and visual inspection as internal agent tools.
- Return recoverable findings to the agent for another turn.
- Surface only irreducible final risks or unverifiable limitations.
- Allow `Auto Fire` only after finalization gates pass.
- Add visual disable toggle.
- Add browser performance logging for visual draw load.
- Add commands such as:
  - "only change drums"
  - "make it brighter but keep the bass"
  - "prepare a break, do not evaluate"
  - "increase energy by 10%"

## Open Questions

- Can failed `editor.evaluate()` ever stop the currently running scheduler before throwing? This needs a targeted test.
- Which Strudel APIs can validate JavaScript and mini-notation without starting audio or visual execution?
- Should early Agent Run state survive backend restarts on local disk, or only browser reconnects within the current process?
- Must every provider support native tool calling, or should the runtime offer a structured-JSON tool-call fallback?
- Which run audit fields are useful for debugging and evaluation without retaining discarded candidate code or hidden reasoning?
- How much of the visual layer should the agent be allowed to modify during live performance?

## Success Criteria

The formal project is viable when:

- The performer can use the embedded REPL exactly like a normal Strudel live coding surface.
- The agent can stage changes without interrupting the current performance.
- The performer can inspect, edit, undo, revise, and fire staged changes.
- The agent repairs recoverable candidate problems internally and stages only a finalized result.
- The agent asks the performer only for material clarification or a key decision, then resumes the same run.
- Long-running model work immediately shows elapsed time, live public commentary, and safe tool activity.
- A cancelled, failed, stale, or budget-exhausted run never changes the editor, playback, snapshots, or change history.
- A bad agent change does not destroy the active performance state.
- The last good version is always recoverable.
- Visuals are useful but never required for audio stability.
