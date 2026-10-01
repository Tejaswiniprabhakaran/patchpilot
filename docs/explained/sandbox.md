# The Docker sandbox, explained

**Code:** `src/patchpilot/sandbox/` · **Half:** SOFTWARE (S1)

## What it does

PatchPilot runs code it did not write: the buggy repository, its tests, and whatever edits the
language model proposes. Any of these could hang forever, eat all the memory, delete files or
try to reach the internet. The sandbox is the one place this code is allowed to run.

A `DockerSandbox` is one Docker container holding one repository checkout. The agent (and the
grader) talk to it through a small API:

| Method | What it does |
|---|---|
| `start()` / `stop()` | create / remove the container (also works as a `with` block) |
| `exec(cmd)` | run a shell command, killed after a time limit |
| `run_tests(cmd)` | run a test command and turn its output into `{test id: PASSED/FAILED/...}` |
| `write_file` / `read_file` | move files in and out |
| `apply_patch(diff)` | apply a unified diff; if it does not apply, nothing changes |
| `diff()` / `reset()` | show / throw away every change since the starting commit |

## Why it is built this way

**Isolation is set when the container is created, not per command.** The container starts with
`network_mode="none"`, so there is no moment when untrusted code has network access. It also gets
a memory limit with no extra swap, a CPU limit, a cap on the number of processes (stops fork
bombs), all Linux capabilities dropped, and `no-new-privileges`.

**No host folders are mounted.** Files go in and out through Docker's archive API (a tar stream).
A bug in the agent therefore cannot write to, or read from, the host machine's disk.

**Every command is wrapped in `timeout -s KILL`.** Some buggy programs loop forever (several
QuixBugs programs do). The sandbox reports `timed_out=True` only when the time limit was actually
reached, so an out-of-memory kill (same exit code, but instant) is not mistaken for a timeout.

**Patches are applied safely.** `git apply` is tried first because it is strict. If it fails, the
more forgiving `patch` tool is used, but only after a `--dry-run` succeeds, so a failed attempt
never leaves a half-applied file behind.

**The parser sees the whole output.** Test logs can be huge. What we store is cut down to the head
and the tail (failures are summarised at the end), but the test-result parser always reads the
full output so no result is lost.

**Containers are labelled** `patchpilot.sandbox`, so `cleanup_orphans()` can remove any left behind
by a crash.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Run tests directly on the host in a virtualenv | No protection at all against malicious or runaway code |
| A new container for every command | Far slower; installing a SWE-bench repo takes minutes |
| Mount the repo from the host | Breaks the "no host mounts" rule and lets bugs touch the host disk |
| Python's `resource` limits instead of Docker | Linux-only, no network isolation, no filesystem isolation |
| gVisor / Firecracker microVMs | Stronger isolation but not available on a student Windows laptop |

## How it is tested

- 26 unit tests with a mocked Docker client check every container option, timeouts, patch
  fallback, file transfer and cleanup.
- 4 integration tests (`pytest -m integration`) run a real QuixBugs container and prove that the
  network is unreachable, a runaway command is killed, and a bad patch leaves the tree untouched.
