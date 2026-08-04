# Workspace Samples

Put local audio in `library/`. Each immediate subdirectory is a Strudel sound
name; supported audio below it becomes zero-based variants in stable path order.
Supported extensions are `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.aif`, and
`.aiff`.

```text
library/
├── kick/
│   ├── deep.wav
│   └── punch.wav
└── vocal.wav
```

After a page refresh, use `s("kick:0 kick:1 vocal")`. The FastAPI backend scans
the directory, generates a Strudel sample map, and serves only mapped audio.
Sound names must contain only letters, digits, `_`, and `-`; symbolic links are
rejected. Audio remains lazy-loaded by Strudel when first played.

`registry.json` is an optional, version-controlled metadata manifest. It can add
tags and descriptions to discovered local sounds, or declare sounds supplied by
an external `samples(...)` map in track code. A registry-only entry does not
register or fetch audio.

Copy `registry.example.json` to `registry.json` and replace its illustrative
entries as needed. Matching is case-insensitive, while the library directory's
spelling is used as the actual Strudel sound name.

The Agent uses the merged catalog through internal `lookup_samples` and
`inspect_sample_usage` tools. The latter compares newly introduced direct
`s()`/`sound()` names with discovered and declared names, then reports
unavailable names for the Agent to repair before finalization. Existing track
code remains authoritative; registry-only entries are advisory and do not
replace runtime loading checks.

The local `GET /samples` endpoint, Agent tools, and workspace Samples panel use
the same merged catalog. The panel reports map registration, not whether every
audio file has already been decoded by WebAudio.
