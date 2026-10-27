# Developer helpers. Source from the repo root:  source scripts/dev/gate.sh
#
#   gate                  run every pre-commit check (format, lint, types, unit tests as CI runs them)
#   commit "msg" paths... commit only if the gate passes, then push
#   pushgh [args]         push as the GitHub CLI's active account
#
# pushgh exists because the Windows credential manager on the development laptop may hold a
# different GitHub account's login; this uses `gh` for the one command and changes no settings.

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=python

gate() {
  "$PY" -m ruff format -q . || return 1
  "$PY" -m ruff check -q . || return 1
  MYPYPATH=src "$PY" -m mypy > /tmp/patchpilot_mypy.txt 2>&1 || { cat /tmp/patchpilot_mypy.txt; return 1; }
  "$PY" -m pytest -q -m "not integration" -p no:cacheprovider > /tmp/patchpilot_pytest.txt 2>&1 \
    || { tail -n 30 /tmp/patchpilot_pytest.txt; return 1; }
  tail -n 1 /tmp/patchpilot_pytest.txt
}

pushgh() {
  git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push "$@"
}

commit() {
  gate || { echo "GATE FAILED - not committing"; return 1; }
  git add "${@:2}" && git commit -q -m "$1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && pushgh -q -u origin HEAD 2>&1 | grep -v '^remote'
  git log --oneline -1
}
