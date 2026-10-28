# The GitHub bot, explained

**Code:** `src/patchpilot/bot/`, `github_action/action.yml` · **Half:** SOFTWARE (S4)

## What it does

When the tests of a pull request fail, the bot tries to fix them and posts its proposal as a comment
on the pull request:

```
pull request ──▶ tests job fails ──▶ PatchPilot job
                                        1. build a sandbox image from the PR's tracked files
                                        2. run the tests (network off) ── pass? stop quietly
                                        3. agent: localize → edit → test → retry
                                        4. re-check the best patch on a fresh checkout
                                        5. comment: the diff + test output before and after
```

**It only comments.** It never pushes a commit, never opens a branch and never merges. A person
reviews the diff and applies it if it is right. The workflow grants the bot `pull-requests: write`
(to comment) and `contents: read` (it cannot change the code).

## Using it in a repository

Copy `github_action/example-workflow.yml` to `.github/workflows/`. Its normal `tests` job runs on
every pull request; the `patchpilot` job runs only `if: failure()`. Inputs:

| Input | Default | Meaning |
|---|---|---|
| `test-command` | `python -m pytest -rA -q` | how to run the tests inside the sandbox |
| `model` | `gemma4:e4b` | model served by Ollama on the runner |
| `llm-base-url` | empty | any OpenAI-compatible endpoint instead of the built-in Ollama |
| `max-attempts` | `2` | repair attempts, each tested before the next |
| `protected-paths` | `tests/` | paths the agent is not allowed to edit |

With the default settings the runner installs Ollama, downloads the model and runs it on the
runner's CPU, so no API key or paid service is needed. The model is downloaded on every run rather
than cached: on GitHub-hosted runners the 5.5 GB Gemma 4 E4B download took 35 s in one run and
85 s in another, a cache restore of the same 5.5 GB is unlikely to be much faster, and the cache
entry would take most of the repository's 10 GB Actions cache allowance.

## Safety

- The pull request's code is untrusted. It runs only inside the same sandbox the experiments use:
  no network, CPU/memory/process limits, all Linux capabilities dropped.
- Dependencies are installed while the image is built, which is the only step with network access.
- Only *tracked* files go into the image, so stray files on the runner (logs, tokens) do not.
- The agent may not edit the tests, so it cannot "fix" a failure by weakening a test.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Push a fix commit or open a fix PR automatically | The brief forbids auto-merging; a comment keeps a human in charge |
| A hosted GitHub App | Needs a server and secrets management; an Action runs inside the user's own CI |
| Calling a paid LLM API by default | Needs an API key per repository; the default runs a local open model (an endpoint can still be configured) |
