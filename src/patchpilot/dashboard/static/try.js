// Try-it page: start one live run and poll its steps until it finishes.
(function () {
  const health = document.getElementById("health");
  const form = document.getElementById("try-form");
  const start = document.getElementById("start");
  const select = document.getElementById("instance");
  const state = document.getElementById("state");
  const steps = document.getElementById("steps");
  const result = document.getElementById("result");
  const resultLine = document.getElementById("result-line");
  const patch = document.getElementById("patch");
  let shown = 0;

  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  async function checkHealth() {
    try {
      const h = await (await fetch("/api/health")).json();
      const ok = h.docker && h.ollama;
      health.textContent = ok
        ? "✓ Docker and Ollama are running: ready for a live run."
        : "⚠ A live run needs both Docker Desktop and Ollama. " +
          "Docker: " + (h.docker ? "running" : "not running") + " · Ollama: " + (h.ollama ? "running" : "not running") + ".";
      health.className = "banner " + (ok ? "good" : "bad");
      start.disabled = !ok || !select.value;
    } catch (e) {
      health.textContent = "⚠ Could not check Docker and Ollama.";
    }
  }

  function addStep(s) {
    const li = el("li", undefined, "step " + s.kind);
    const details = el("details");
    const summary = el("summary");
    summary.append(el("span", s.kind, "kind"), el("span", s.name, "name"),
      el("span", s.ok ? "✓" : "✗", s.ok ? "good" : "bad"), el("span", s.duration_s.toFixed(1) + " s", "muted"));
    details.append(summary, el("pre", s.output));
    li.append(details);
    steps.append(li);
  }

  async function poll(runId) {
    const r = await fetch("/api/try/" + encodeURIComponent(runId));
    if (!r.ok) { state.textContent = "Lost track of the run."; return; }
    const data = await r.json();
    data.steps.slice(shown).forEach(addStep);
    shown = data.steps.length;
    if (data.state === "running") {
      state.textContent = "Running… " + shown + " steps so far.";
      setTimeout(() => poll(runId), 2000);
      return;
    }
    state.textContent = "";
    result.hidden = false;
    const res = data.result || {};
    resultLine.textContent = data.state === "error"
      ? "⚠ The run stopped with an error: " + data.error
      : (res.resolved ? "✓ Resolved" : "✗ Not resolved") + " in " + res.attempts_used + " attempt(s), " +
        Math.round(res.wall_s || 0) + " s, " + (res.llm_calls || 0) + " model calls.";
    patch.innerHTML = data.patch_html;  // server-rendered, escaped by Pygments
    start.disabled = false;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    start.disabled = true;
    steps.replaceChildren();
    result.hidden = true;
    shown = 0;
    state.textContent = "Starting…";
    const r = await fetch("/api/try", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instance_id: select.value }),
    });
    const data = await r.json();
    if (!r.ok) {
      state.textContent = "⚠ " + (data.detail || "Could not start the run.");
      start.disabled = false;
      return;
    }
    poll(data.run_id);
  });

  checkHealth();
})();
