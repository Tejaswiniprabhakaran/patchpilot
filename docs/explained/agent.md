# The agent, explained

**Code:** `src/patchpilot/agent/`, `src/patchpilot/tools/`, `src/patchpilot/llm/` ·
**Half:** SOFTWARE (S2), with the model calls feeding AI (A1–A4)

## What it does

Given a bug (a description plus a failing test), the agent produces a patch and proves it works.

```
prepare  ->  run tests (see the failure)  ->  localize files  ->  read code
                                                                     |
                 +-------------------- attempt 1..N ------------------+
                 |  ask the model for an edit  ->  apply it  ->  run tests
                 |        ^                                          |
                 |        +-------- test output fed back ------------+   (if still failing)
                 +----------------------------------------------------
submit the best candidate  ->  grade it on a fresh checkout (official resolution rule)
```

### The tools

The agent can touch the repository only through six tools (`Toolbox`), all running inside the
Docker sandbox:

| Tool | What it does | Safety rule |
|---|---|---|
| `list_files` | tracked files (`git ls-files`) | at most 400 |
| `read_file(path, start, end)` | numbered lines | path must stay inside the repo |
| `search_code(query)` | fixed-string search (ripgrep, or `git grep` if the image lacks it) | at most 50 hits |
| `edit_file(path, search, replace)` | replace one exact block | must match exactly once; test files refused; Python must still compile or the edit is undone |
| `run_tests` | run the target tests, summarise passes, failures and broken tests | |
| `submit` | the diff of all changes except test files | |

A tool never crashes on a bad request from the model; it returns `ok=False` with a reason
("the SEARCH block matches 2 places; include more lines"). That reason is shown to the model,
which can then correct itself.

### Edits as SEARCH/REPLACE blocks

The model answers with blocks like:

```
pkg/mod.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
```

We chose this over asking for a unified diff because small open models get line numbers and
hunk headers wrong, while copying a few lines of code is easy for them. If the copy is slightly off
(indentation, trailing spaces) a whitespace-tolerant match is tried before giving up.

### Retries with feedback

If the tests still fail, the next attempt's prompt contains the previous edit and the test output.
**Every attempt starts from the original code**, so a bad edit never piles up under the next one.
Of all the candidates, the best is submitted: a fully passing one if any, otherwise the one passing
the most target tests while breaking the fewest. Setting `max_attempts: 1` turns retries off (E4).

### Localization is pluggable

`Localizer` is an interface. The baseline, `LLMSearchLocalizer` (used by B0 and E2), works like
this:
1. the model reads the bug report and failing tests and proposes up to five identifiers and files;
2. the agent searches the code for those identifiers;
3. candidates (from the search, the model's guesses and file paths in the traceback, minus test
   files) are ranked by the model, and the top 3 files are read.

The trained ranker from Phase 3 (A1) implements the same interface, which is what makes the
RQ2 comparison (B0 against E1) a clean one-variable change.

### Everything is recorded

Every tool call and model call becomes a `Step` in a `Trajectory`: inputs, output, success,
duration and, for model calls, prompt and completion tokens. Trajectories are saved as JSON
(gzipped for experiments) and are the raw material for the dashboard and the failure analysis
(A5). Environment failures (Docker errors, timeouts) are recorded as results, not crashes.

### The model client

`OpenAICompatibleClient` speaks the OpenAI chat API, which Ollama, vLLM, llama.cpp and Gemini
all offer, so changing model is a config change (`llm.base_url`, `llm.model`). Temperature 0 and a
fixed seed keep runs as repeatable as the server allows. `ScriptedClient` replays fixed answers so
the whole loop is unit-tested without a model.

## An important methodological choice

The agent **sees the failing test** (for SWE-bench, the test patch is applied at the start). This
matches the brief's scenario of a CI bot reacting to a failing test on a pull request. The
official SWE-bench leaderboard hides those tests, so **our SWE-bench numbers are not directly
comparable to leaderboard numbers**; this is stated wherever results are reported. Edits to test
files are refused, and grading uses the official eval script, which resets test files first, so
the agent cannot "fix" a bug by changing its test.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Free-form tool calling (the model decides every step) | Small open models lose track over long tool-calling sessions; a fixed pipeline with model decisions at each stage is more reliable at 4–12B scale |
| Unified diffs from the model | Line numbers and hunk headers are error-prone for small models |
| Keep editing on top of failed attempts | Errors accumulate; starting fresh with feedback is cleaner and easier to analyse |
| LangChain / agent frameworks | Hides the loop we must explain and evaluate; adds heavy dependencies |
