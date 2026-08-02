# Pinned Strudel knowledge

This directory is the offline Strudel reference used by Agent Runs. Runtime
code reads only these checked-in files and never fetches documentation.

- `skill.md` contains the short operating guidance injected into every Run.
- `corpus.json` contains normalized tutorial sections and API references.
- `manifest.json` pins source versions and verifies the corpus checksum.
- `LICENSE.strudel` is the upstream license distributed with the source data.

The corpus combines the official `learn`, `workshop`, and `recipes` MDX from
the `@strudel/repl@1.3.0` source tag with structured function metadata from
`@strudel/reference@1.2.2`. It expands `MiniRepl` examples and `JsDoc`
references during generation.

Regenerate it explicitly after changing the pinned Strudel runtime:

```bash
python3 scripts/sync_strudel_knowledge.py
```

The sync command requires network access and Node.js. Review the manifest,
corpus diff, license, and backend search tests before committing an update.
