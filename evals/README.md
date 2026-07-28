# Evaluation Baseline

This directory contains fixed, version-controlled musical capability scenarios.
They are not unit tests and do not call a model by themselves.

Each JSON scenario defines a source fixture, an optional project-context fixture,
the performer intent, deterministic region expectations, and a short human
review rubric. Region markers in the Strudel fixtures make preservation and
change checks possible without treating musical quality as a binary assertion.

`backend/app/evaluations.py` loads and validates the files. Scenario evaluation
has three layers: deterministic final/region checks, Agent Run tool/loop
observations, and separately entered human musical review.

The deterministic assessment already compares the final outcome with the
scenario expectation, checks marked regions, and runs the existing
non-performing `validate_candidate` gate. Its `syntaxValid` field means that
current gate passed; it is not a substitute for the deeper Strudel validation
work planned for Phase 5.

`execute_scenario()` accepts an explicit Provider and runs the scenario in an
isolated Agent Run. Its safe report includes terminal/action outcome, whether a
fixture editor update was applied, usage, and tool name/status/error-code
observations. It does not store Provider credentials, raw tool output, candidate
code, or clarification reasons.

After listening to the result, a reviewer uses `create_human_review()` to mark
each fixed rubric item as `met`, `partial`, `not_met`, or `not_applicable`, give
an optional 1–5 musical-quality score, and mark performance readiness. The
review cannot add free-text notes or arbitrary criteria, so the persisted result
cannot accidentally become a second candidate-code or secret store.

`save_evaluation_record()` appends the safe report and review under
`evals/results/`, which is intentionally ignored by Git. `list_evaluation_records()`
preserves the run history; `summarize_evaluation_records()` uses only the latest
record for each scenario so repeated tuning runs do not inflate coverage.

Scenario expectations describe the final user-facing outcome only. They never
require a provider's hidden reasoning, intermediate candidates, or an exact
generated code string.
