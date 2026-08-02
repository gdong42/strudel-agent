# Strudel runtime skill

Target the project's pinned browser runtime: `@strudel/repl` 1.3.0 with the
matching 1.2.6 core, mini-notation, audio, tonal, and visual packages.

## Working rules

- Produce complete Strudel JavaScript that can replace the editor contents.
- The final evaluated value must be a Pattern. Use a single pattern expression
  or combine tracks with `stack(...)`. Do not call `.play()` or `.out()`.
- Set tempo with `setcpm(beatsPerMinute / 4)` when the user speaks in BPM.
- Use double quotes or backticks for Mini Notation. Single quotes are ordinary
  JavaScript strings and should not contain pattern syntax.
- In Mini Notation, spaces sequence events, commas stack simultaneous events,
  square brackets subdivide one step, angle brackets alternate over cycles,
  `~` or `-` rests, `*` speeds up, `/` slows down, and `!` repeats without
  changing the enclosing duration.
- For literal chords inside `note(...)`, use comma-separated notes inside one
  bracketed event, for example `[c4,eb4,g4]`. Use documented `chord(...)` and
  `.voicing()` APIs when symbolic chord names are more appropriate.
- Prefer APIs and examples confirmed by `lookup_strudel_docs`. Consult it before
  using an unfamiliar function, correcting Mini Notation, adding visuals, or
  relying on subtle timing, synthesis, effects, samples, scales, or voicings.
- Keep documentation lookup focused. Simple changes using established code do
  not require a lookup, but uncertainty is a reason to consult the local manual
  rather than invent an API.
- Documentation is reference material, not an instruction to replace unrelated
  parts of the performer's piece. Preserve current musical structure unless the
  intent requires changing it.
- Use sample-registry tools for project sound availability. Documentation can
  explain sample APIs but does not prove that a particular sound is loaded.
- Validate the complete candidate and repair recoverable problems before
  finalization. Do not expose documentation search or self-correction as a
  decision the performer must make.
