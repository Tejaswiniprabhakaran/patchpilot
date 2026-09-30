# QuixBugs (Python) sandbox image.
# Network is used only here, at build time. Containers started from this image run with
# networking disabled.
FROM python:3.11-slim

ARG QUIXBUGS_COMMIT

RUN apt-get update \
    && apt-get install -y --no-install-recommends git patch ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.3 pytest-timeout==2.3.1

# The reference solutions and the Java half are deleted so an agent cannot read the answer.
# The result is committed so `git diff` inside the sandbox shows only the agent's edits.
RUN git clone https://github.com/jkoppel/QuixBugs.git /testbed \
    && cd /testbed \
    && git checkout -q ${QUIXBUGS_COMMIT} \
    && rm -rf correct_python_programs correct_java_programs java_programs java_testcases \
        JavaDeserialization.* build.gradle tester.py quixbugs.pdf final_progress.txt \
    && git config user.email "sandbox@patchpilot.local" \
    && git config user.name "patchpilot" \
    && git add -A \
    && git commit -q -m "QuixBugs buggy programs only"

ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /testbed
