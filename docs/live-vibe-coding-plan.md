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
- Progressive disclosure: beginners can stay in natural language and high-level controls; experienced Strudel users can work directly in the editor.
- Local-first for performance: the live runtime should not depend on network availability once required packages and samples are available.

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

Agent requests may include constraints:

- scope: "only change drums", "do not touch bass", "visuals only"
- intensity: "subtle", "more energetic", "make it peak"
- timing: "prepare a break", "make a drop for the next section"
- protection: "keep the current groove", "do not add low-end"

The agent should explain proposed changes in musical terms, not only code terms. For example, it should say that it tightened the bass rhythm, brightened the hats, or moved a pad out of the low-frequency range.

### Agent Apply Mode

The product should expose only two agent apply modes:

- `Manual Fire`: the agent stages changes directly into the editor, shows a diff or change summary, and waits. The user decides when to evaluate with `Ctrl+Enter` or `Evaluate`. This is the default mode.
- `Auto Fire`: the agent stages and evaluates changes automatically after validation. This is opt-in and intended for exploration, rehearsal, or low-risk situations.

`Manual Fire` deliberately has no separate "accept" step. The agent's response becomes an editable staged change in the REPL immediately, but it does not affect the running music until the user fires it. The user can review the diff, undo the staged change, keep editing, or ask the agent to revise.

### Agent Staging Flow

When the user gives a natural language prompt in `Manual Fire` mode:

1. The agent reads the current track, musical context, and user constraints.
2. The agent generates a change and stages it directly in the editor.
3. The app shows a diff from the previous editor contents, a short musical explanation, and any warnings.
4. The user can fire it, undo it, manually edit it, or ask the agent to revise it.

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

The app should handle at least:

- JavaScript syntax errors.
- Strudel mini-notation parse errors.
- Unknown sample names.
- Failed sample loading.
- Visual feedback errors.
- Runtime audio errors.
- Server disconnects.

On error:

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
  ├─ agent change API
  ├─ agent service / change engine
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

- Agent layer: convert user intent into proposed musical changes, explanations, warnings, and diffs.
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

This separation supports both product directions:

- In agent-first flows, generated work can appear immediately in the editor without becoming active.
- In manual live coding flows, the user can directly edit and evaluate without waiting for the agent.
- In `Manual Fire`, generated changes can be staged without disrupting the running set.

Sync rules:

- The visible editor is the source of truth while a browser session is active.
- Agent-generated changes are staged directly into the editor in `Manual Fire`.
- Staging a change records `preAgentEditorCode` and `changeSet` so the user can inspect or undo it.
- Browser edits are saved to disk on evaluate and optionally on debounce.
- If the user has unsaved local editor changes, do not replace them without confirmation.
- If the agent produces a change while the editor is dirty, create the diff against the current visible editor contents.

Evaluation rules:

- `Manual Fire` requires human action with `Ctrl+Enter` or `Evaluate`.
- `Auto Fire` can stage and evaluate changes automatically after validation.
- `Stop` stops playback and disarms automatic evaluation.
- `Panic` should stop playback, clear visuals, and optionally reload the REPL frame.
- Successful evaluation records a snapshot and updates `lastGoodCode`.
- Failed evaluation must not overwrite `lastGoodCode`.

The current POC auto-applies file changes into the editor and can auto-evaluate after the page is armed. The formal product should keep the first behavior for `Manual Fire` but not the second: agent changes may stage into the editor automatically, but evaluation should remain a user action unless `Auto Fire` is explicitly enabled.

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
│     ├─ agent.py
│     ├─ changes.py
│     ├─ tracks.py
│     ├─ snapshots.py
│     ├─ samples.py
│     ├─ config.py
│     ├─ models.py
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
├─ samples/
├─ project.config.json
├─ agent-context.md
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

- Add staged change endpoints:
  - `POST /changes`
  - `GET /changes/latest`
  - `POST /changes/:id/undo`
- Show side-by-side or inline diff.
- Agent changes update the editor but do not evaluate in `Manual Fire`.
- Staged changes remain in history for review and recovery.
- Show musical explanation and warnings for each staged change.

### Phase 4: Agent Integration and Prompt Contract

- Define a structured instruction format:
  - musical intent
  - scope
  - constraints
  - intensity
  - avoid list
- Let the agent generate staged changes against the current editor contents.
- Store prompts and staged changes in `changes/`.
- Add agent context from `agent-context.md`.
- Add optional project conventions:
  - `mood`
  - stems: drums, bass, chords, pad, lead, fx
  - arrangement markers.

### Phase 5: Validation and Performance Hardening

- Add warnings for missing known samples.
- Add warnings for risky sample or visual changes in `Auto Fire`.
- Add visual disable toggle.
- Add browser performance logging for visual draw load.
- Add commands such as:
  - "only change drums"
  - "make it brighter but keep the bass"
  - "prepare a break, do not evaluate"
  - "increase energy by 10%"

## Open Questions

- Can failed `editor.evaluate()` ever stop the currently running scheduler before throwing? This needs a targeted test.
- Should staged changes be full-file replacements or structured patches? Full-file is simpler; patches are safer for review.
- Should the agent operate directly on Strudel JS, or on a higher-level song model that compiles to Strudel?
- How much of the visual layer should the agent be allowed to modify during live performance?
- Should browser edits autosave on debounce, or only on evaluate?

## Success Criteria

The formal project is viable when:

- The performer can use the embedded REPL exactly like a normal Strudel live coding surface.
- The agent can stage changes without interrupting the current performance.
- The performer can inspect, edit, undo, revise, and fire staged changes.
- A bad agent change does not destroy the active performance state.
- The last good version is always recoverable.
- Visuals are useful but never required for audio stability.
