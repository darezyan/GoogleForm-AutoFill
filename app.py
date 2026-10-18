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
