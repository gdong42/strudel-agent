# Strudel Agent

Strudel Agent is a local development prototype for live vibe coding with Strudel.

It embeds the official Strudel REPL in a local web app, keeps the current track in `tracks/main.strudel.js`, and uses a small FastAPI backend to read/write the track and notify the browser when it changes.

The long-term goal is to add an agent layer so music can be changed through natural language while still keeping the Strudel code visible and directly editable.

## Development

Install frontend dependencies:

```bash
npm install
```

Install backend dependencies:

```bash
UV_CACHE_DIR=../.uv-cache uv sync --project backend
```

Start the backend:

```bash
cd backend
UV_CACHE_DIR=../.uv-cache uv run uvicorn app.main:app --host 127.0.0.1 --port 8787
```

For local Provider payload diagnostics, add `--log-level debug`. Streaming
responses are logged once per completed stream as a bounded aggregate instead
of once per token event. Debug logs include model prompts and responses, so
enable them only in a trusted terminal.

Start the frontend in another terminal:

```bash
npm run dev -- --port 5173
```

Open:

```text
http://127.0.0.1:5173/
```

## Strudel Knowledge

The version-matched Strudel skill and manual are checked into the repository,
so first-time setup and normal Agent Runs do not download documentation or
require documentation network access.

After upgrading the pinned Strudel packages, regenerate the offline knowledge
package from the repository root:

```bash
python3 scripts/sync_strudel_knowledge.py
```

The sync command requires network access and Node.js. Review the generated
manifest and corpus diff, then run the test suites before committing the
updated knowledge package.

## Tests

```bash
npm test
cd backend && UV_CACHE_DIR=../.uv-cache uv run pytest
npm run test:e2e:mock
```
