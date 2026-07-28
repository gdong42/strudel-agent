# Sample Registry

`registry.json` is an optional, version-controlled manifest of sound names that
the project has deliberately made available to the Strudel REPL. It is a source
of truth for the Agent, not a downloader and not a claim that a sound is loaded
at this exact moment.

Copy `registry.example.json` to `registry.json` and replace its illustrative
entries with names registered by this workspace's REPL startup code or local
sample setup. Adding a name to the manifest does not register or fetch audio.

The Agent uses this manifest through internal `lookup_samples` and
`inspect_sample_usage` tools. The latter compares newly introduced direct
`s()`/`sound()` names with the manifest and reports undeclared names for the
Agent to repair before finalization. Existing track code remains authoritative;
the registry is advisory and does not replace runtime loading checks.

The local `GET /samples` endpoint and workspace Samples panel show the same
declared catalog. They intentionally do not label any sound as loaded, playing,
or otherwise verified by the live REPL.
