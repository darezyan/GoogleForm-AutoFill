# Browser front end for FormFiller: run `python app.py` and it opens in your browser

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from FormFiller import FormError, build_payload, load_form, submit, unanswerable

PORT = 8765


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows, reuse lets a second copy share the port silently

state = {"running": False, "ok": 0, "done": 0, "total": 0, "log": [], "stop": False}
lock = threading.Lock()


def log(msg):
    with lock:
        state["log"].append(msg)


def read_form(link):
    """Returns (form, None) or (None, error message for the page)."""
    try:
        return load_form(link), None
    except FormError as e:
        return None, str(e)
    except requests.RequestException as e:
        return None, f"Couldn't open the link: {e}"
    except Exception as e:  # Google changed its page layout, or the link isn't a form
        return None, f"Couldn't read this form ({type(e).__name__}: {e})."


def run(link, count, delay, overrides, email):
    try:
        form, error = read_form(link)
        if error:
            log(error)
            return
        missing = unanswerable(form, overrides)
        if missing:
            log("These required questions need a fixed answer: " + ", ".join(missing))
            return

        session = requests.Session()
        for i in range(1, count + 1):
            if state["stop"]:
                log("Stopped.")
                break
            try:
                success, message = submit(session, form, build_payload(form, overrides, email))
                state["ok"] += success
            except requests.RequestException as e:
                message = f"Error: {e}"
            log(f"[{i}/{count}] {message}")
            state["done"] = i
            if i < count and not state["stop"]:
                time.sleep(delay)
        log(f"Done: {state['ok']}/{count} submitted.")
    except Exception as e:
        log(f"Unexpected error, stopped: {type(e).__name__}: {e}")
    finally:
        state["running"] = False


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            with lock:
                self.send_json({k: state[k] for k in ("running", "ok", "done", "total", "log")})
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send_json({"error": "Bad request."}, 400)

        if self.path == "/api/load":
            form, error = read_form(data.get("link", ""))
            if error:
                return self.send_json({"error": error}, 400)
            return self.send_json({
                "pages": form["pages"],
                "questions": form["questions"],
                "collects_email": form["collects_email"],
                "missing": unanswerable(form, {}),
            })

        if self.path == "/api/start":
            if state["running"]:
                return self.send_json({"error": "Already running."}, 409)
            try:
                count = int(data.get("count") or 0)
                delay = max(float(data.get("delay") or 0), 0)
            except ValueError:
                return self.send_json({"error": "How many times and the wait must be numbers."}, 400)
            try:
                overrides = json.loads(data.get("answers") or "{}")
            except ValueError as e:
                return self.send_json({"error": f"Fixed answers aren't valid JSON: {e}"}, 400)
            if not isinstance(overrides, dict):
                return self.send_json({"error": 'Fixed answers must look like {"Question title": "answer"}.'}, 400)
            if count < 1:
                return self.send_json({"error": "How many times must be at least 1."}, 400)
            if not data.get("link", "").strip():
                return self.send_json({"error": "Paste the form link first."}, 400)
            state.update(running=True, ok=0, done=0, total=count, log=[], stop=False)
            threading.Thread(
                target=run,
                args=(data["link"], count, delay, overrides, data.get("email") or None),
                daemon=True,
            ).start()
            return self.send_json({"started": True})

        if self.path == "/api/stop":
            state["stop"] = True
            return self.send_json({"stopping": True})

        self.send_error(404)

    def log_message(self, *args):
        pass  # keep the terminal quiet


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Form Filler</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#667085; --line:#d9dde5; --accent:#5b4fe0; --ok:#1a7f4b; --bad:#c0392b; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14161b; --card:#1d2027; --text:#e7e9ee; --muted:#9aa1ae; --line:#2e323c; --accent:#8b80ff; --ok:#4cc38a; --bad:#ff7a6b; }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui, sans-serif; }
  main { max-width:720px; margin:32px auto; padding:0 16px; }
  h1 { font-size:22px; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:18px; margin-bottom:16px; }
  label { display:block; font-weight:600; margin:12px 0 4px; }
  label:first-child { margin-top:0; }
  small { color:var(--muted); font-weight:400; }
  input, textarea { width:100%; padding:9px 10px; border:1px solid var(--line); border-radius:7px; background:var(--bg); color:var(--text); font:inherit; }
  textarea { font-family:ui-monospace, monospace; font-size:13px; min-height:80px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; }
  .row > div { flex:1; min-width:140px; }
  button { padding:9px 16px; border-radius:7px; border:1px solid var(--accent); background:var(--accent); color:#fff; font:inherit; font-weight:600; cursor:pointer; }
  button.ghost { background:transparent; color:var(--accent); }
  button:disabled { opacity:.5; cursor:default; }
  .actions { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
  ul { margin:8px 0 0; padding-left:20px; }
  .req { color:var(--bad); }
  .opts { color:var(--muted); font-size:13px; }
  .err { color:var(--bad); }
  .hint { color:var(--muted); font-size:13px; margin:8px 0 0; }
  .bar { height:8px; background:var(--line); border-radius:4px; overflow:hidden; margin:8px 0; }
  .bar > div { height:100%; width:0; background:var(--ok); transition:width .3s; }
  pre { margin:0; max-height:240px; overflow:auto; font-size:13px; white-space:pre-wrap; }
  .hidden { display:none; }
</style>
</head>
<body>
<main>
  <h1>Form Filler</h1>
  <p class="sub">Paste a Google Form link, pick how many responses to send, and start.</p>

  <div class="card">
    <label for="link">Form link <small>(the share link ending in /viewform, or forms.gle)</small></label>
    <input id="link" placeholder="https://docs.google.com/forms/d/e/.../viewform">
    <div class="row">
      <div><label for="count">How many times</label><input id="count" type="number" min="1" value="5"></div>
      <div><label for="delay">Wait after each (seconds)</label><input id="delay" type="number" min="0" step="0.5" value="2"></div>
      <div><label for="email">Email <small>(optional)</small></label><input id="email" placeholder="if the form asks"></div>
    </div>
    <p class="hint">It sends one response, waits this many seconds, then sends the next. 300 responses at 2 seconds takes about 10 minutes. Sending too fast can get you blocked by Google.</p>
    <label for="answers">Fixed answers <small>(optional JSON, by question title; a list picks one at random)</small></label>
    <textarea id="answers" placeholder='{"Name": "Test User", "Age group": ["18-24", "25-34"]}'></textarea>
    <div class="actions">
      <button class="ghost" id="loadBtn">Check form</button>
      <button id="startBtn">Start</button>
      <button class="ghost hidden" id="stopBtn">Stop</button>
    </div>
    <p id="msg" class="err"></p>
  </div>

  <div class="card hidden" id="formCard">
    <strong id="formTitle"></strong>
    <p id="formNotes" class="hint"></p>
    <ul id="qList"></ul>
  </div>

  <div class="card hidden" id="progCard">
    <strong id="progText"></strong>
    <div class="bar"><div id="progBar"></div></div>
    <pre id="logBox"></pre>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
let timer = null;

async function api(path, body) {
  const res = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : undefined);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
}

function esc(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

$("loadBtn").onclick = async () => {
  $("msg").textContent = "";
  $("loadBtn").disabled = true;
  try {
    const data = await api("/api/load", {link: $("link").value});
    $("formTitle").textContent = `Found ${data.questions.length} question(s) on ${data.pages} page(s)`;
    const notes = [];
    if (data.collects_email) notes.push("This form collects emails. Your email box is used, or a test address if it's empty.");
    if (data.missing.length) notes.push("Set these under Fixed answers before starting (they have a custom format rule): " + data.missing.join(", "));
    $("formNotes").textContent = notes.join(" ");
    $("formNotes").className = data.missing.length ? "err" : "hint";
    $("qList").innerHTML = data.questions.map(q =>
      `<li>${q.required ? '<span class="req">*</span> ' : ''}${esc(q.title || "(untitled)")}` +
      (q.options.length ? `<div class="opts">${esc(q.options.join(" · "))}</div>` : "") + `</li>`).join("");
    $("formCard").classList.remove("hidden");
  } catch (e) { $("msg").textContent = e.message; }
  $("loadBtn").disabled = false;
};

$("startBtn").onclick = async () => {
  $("msg").textContent = "";
  try {
    await api("/api/start", {link: $("link").value, count: $("count").value, delay: $("delay").value,
                             email: $("email").value, answers: $("answers").value});
    $("progCard").classList.remove("hidden");
    poll();
  } catch (e) { $("msg").textContent = e.message; }
};

$("stopBtn").onclick = () => api("/api/stop", {});

async function poll() {
  clearTimeout(timer);
  let s;
  try { s = await api("/api/status"); }
  catch (e) { $("progText").textContent = "Lost connection to the app. Is the terminal still running?"; timer = setTimeout(poll, 3000); return; }
  $("progText").textContent = s.running ? `Sending… ${s.done}/${s.total}` : `Finished: ${s.ok}/${s.total} submitted`;
  $("progBar").style.width = s.total ? (100 * s.done / s.total) + "%" : "0";
  $("logBox").textContent = s.log.join("\\n");
  $("logBox").scrollTop = $("logBox").scrollHeight;
  $("startBtn").disabled = s.running;
  $("stopBtn").classList.toggle("hidden", !s.running);
  if (s.running) timer = setTimeout(poll, 700);
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"Form Filler is already running. Opening {url}")
        webbrowser.open(url)
        raise SystemExit
    print(f"Form Filler running at {url}  (press Ctrl+C to quit)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
