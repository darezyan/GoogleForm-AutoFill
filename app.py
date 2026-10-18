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
