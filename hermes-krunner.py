#!/usr/bin/python3
"""hermes-krunner — از «هرمس» در KRunner (Alt+F2) سؤال بپرس.

A KRunner D-Bus runner (interface ``org.kde.krunner1``) that sends a question to
Hermes Agent and shows the answer inside KRunner.

How the question gets to Hermes:
  1. The running Hermes **desktop app** (its local ``hermes serve`` JSON-RPC
     backend) — the question is submitted as a real turn in a dedicated chat, so
     it shows up in the app exactly like a typed message, and the answer streams
     there as well;
  2. if the app is not running it is launched first (``hermes desktop``);
  3. if it cannot be reached at all, the headless ``hermes chat -q`` engine
     answers instead (nothing needs to be running for that).

Run modes:
  hermes-krunner.py                 # serve the D-Bus interface (what KRunner calls)
  hermes-krunner.py --ask "سؤال"    # ask once, print the answer (same engines/cache)
  hermes-krunner.py --match "? سؤال"  # print the matches KRunner would get (JSON)
  hermes-krunner.py --status        # backend / app state
  hermes-krunner.py --stop          # stop a running service (picks up code edits)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import unicodedata
from html import escape as html_escape
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
HOME = Path(os.path.expanduser("~"))
CONFIG_PATH = Path(os.environ.get("HERMES_KRUNNER_CONFIG") or HOME / ".config/hermes-krunner/config.json")
STATE_DIR = Path(os.environ.get("HERMES_KRUNNER_STATE") or HOME / ".cache/hermes-krunner")
CACHE_PATH = STATE_DIR / "answers.json"
LOG_PATH = STATE_DIR / "hermes-krunner.log"
PID_PATH = STATE_DIR / "service.pid"

BUS_NAME = os.environ.get("HERMES_KRUNNER_BUS") or "org.maxv.hermeskrunner"
OBJECT_PATH = os.environ.get("HERMES_KRUNNER_OBJECT") or "/runner"
IFACE = "org.kde.krunner1"

DEFAULTS: dict = {
    # Words that put KRunner into "ask Hermes" mode. Case/ك-ی insensitive.
    "triggers": ["?", "؟", "hermes", "هرمس", "ana", "آنا", "kattie", "کتی"],
    # Title of the chat the questions land in, inside the desktop app.
    "session_title": "⚡ پرسش سریع",
    # "auto" = desktop app first, headless CLI if the app can't be reached.
    "engine": "auto",  # auto | app | cli
    # Bring the desktop app up when a question arrives and it is not running.
    "launch_app_if_down": True,
    # How long to wait for a freshly launched app's backend before giving up.
    "app_start_timeout_s": 60,
    # How long a KRunner match may hold its reply waiting for the answer
    # (KRunner's own D-Bus timeout is 25s — stay well below it).
    "inline_wait_s": 18,
    # Hard cap on a single ask.
    "answer_timeout_s": 240,
    # Start a fresh chat once the quick-ask chat has this many messages.
    "session_rotate_after_messages": 60,
    # Answered questions kept on disk for instant re-display.
    "cache_size": 120,
    # Answer text shown inside the KRunner match (Enter opens Hermes, nothing is copied).
    "inline_answer_chars": 1500,
    # 3 = lowest, 30 = low, 50 = moderate, 70 = high, 100 = highest (KRunner category relevance)
    "answer_category_relevance": 100,
    "hint_category_relevance": 70,
    "show_hint_when_empty": True,
    # Nothing is sent to the model while you are just typing:
    # a query is asked when you press Enter, use a trigger word, or type "?".
    "auto_ask": True,
    "auto_ask_on_question_mark": True,
    "debounce_ms": 700,
    "min_question_chars": 3,
    # Plain queries (no trigger word) still get a "از هرمس بپرس: …" suggestion row.
    "suggest_untriggered": True,
    "min_suggest_chars": 3,
    "suggest_relevance": 0.5,
    "suggest_category_relevance": 50,
    "notify": True,
    "notify_inline_answers": False,
    # KWin window classes of the desktop app, used to raise its window on Enter.
    "app_window_class": ["com.nousresearch.hermes"],
    "hermes_bin": "",  # empty = resolve from PATH / ~/.local/bin
    "cli_extra_args": ["--oneshot", "-Q", "--source", "krunner"],
    "log_level": "INFO",
    # Stop the service after this many minutes without a query (0 = never).
    "idle_exit_minutes": 20,
}


# ── logging ──────────────────────────────────────────────────────────────────
log = logging.getLogger("hermes-krunner")


def setup_logging(level: str = "INFO", to_stderr: bool = False) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
        try:
            os.chmod(LOG_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        to_stderr = True
    if to_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        log.addHandler(sh)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("config %s unreadable (%s) — using defaults", CONFIG_PATH, exc)
    return cfg


# ── query helpers (pure) ─────────────────────────────────────────────────────
_ZWNJ = "\u200c"


def normalize_text(text: str) -> str:
    """Lower-case and fold the Persian/Arabic variants that look identical."""
    if not text:
        return ""
    out = unicodedata.normalize("NFC", str(text))
    out = out.replace("ي", "ی").replace("ك", "ک").replace("\u0649", "ی")
    out = out.replace("ۀ", "ه").replace("\u0623", "ا").replace("\u0625", "ا")
    out = out.replace(_ZWNJ, " ").replace("\u200f", "").replace("\u200e", "")
    out = re.sub(r"\s+", " ", out)
    # "استرالیا ؟" and "استرالیا؟" are the same question.
    out = re.sub(r"\s+([؟?!.,،؛:;])", r"\1", out)
    return out.strip().lower()


def strip_trigger(query: str, triggers: list) -> tuple:
    """Return ``(is_ask, question)`` for a raw KRunner query."""
    raw = re.sub(r"\s+", " ", str(query or "").strip())
    if not raw:
        return False, ""
    folded = normalize_text(raw)
    candidates = []
    for trig in triggers or []:
        t = normalize_text(str(trig))
        if t:
            candidates.append(t)
    # Longest first, so "hermes" wins over "he".
    for trig in sorted(set(candidates), key=len, reverse=True):
        if not folded.startswith(trig):
            continue
        rest = raw[len(trig):] if len(raw) >= len(trig) else ""
        # Punctuation triggers ("?") may be glued to the question; word triggers need a break.
        glued_ok = not trig[-1].isalnum()
        if rest and rest[0].isalnum() and trig[-1].isalnum():
            continue
        if rest and rest[0] not in " \t:،,." and trig[-1].isalnum() and not glued_ok:
            continue
        question = rest.lstrip(" \t:،,.").strip()
        return True, question
    return False, ""


def question_key(question: str) -> str:
    return normalize_text(question)


def classify_query(cfg: dict, raw: str) -> dict:
    """Decide what a KRunner query means. Pure — the D-Bus path stays thin.

    Nothing is ever sent to the model just because text is being typed. A query is
    only asked when the user *signals* it: a trigger word, a question mark, or Enter.

    modes:
      ``ignore``  — nothing worth showing (empty / too short)
      ``hint``    — only a trigger was typed ("?"), teach the syntax
      ``suggest`` — a plain query: offer "از هرمس بپرس: <query>" (no model call yet)
      ``manual``  — triggered query with ``auto_ask`` off: offer the row, ask on Enter
      ``ask``     — signaled (trigger, "?", or via Enter on another path): ask now
    """
    raw = re.sub(r"\s+", " ", str(raw or "").strip())
    triggered, stripped = strip_trigger(raw, cfg.get("triggers") or [])
    min_q = int(cfg.get("min_question_chars") or 3)
    min_s = int(cfg.get("min_suggest_chars") or 3)
    auto = bool(cfg.get("auto_ask", True))
    if not raw:
        return {"raw": raw, "triggered": False, "question": "", "mode": "ignore"}
    if triggered:
        if len(stripped) < min_q:
            return {"raw": raw, "triggered": True, "question": stripped, "mode": "hint"}
        return {"raw": raw, "triggered": True, "question": stripped,
                "mode": "ask" if auto else "manual"}
    if len(raw) < min_s:
        return {"raw": raw, "triggered": False, "question": raw, "mode": "ignore"}
    if not bool(cfg.get("suggest_untriggered", True)):
        return {"raw": raw, "triggered": False, "question": raw, "mode": "ignore"}
    # A question mark anywhere in the text is an explicit "ask this" signal, so a
    # finished sentence ("… چی بود؟") goes straight to Hermes without an Enter.
    marked = bool(cfg.get("auto_ask_on_question_mark", True)) and any(
        ch in raw for ch in ("?", "؟"))
    return {"raw": raw, "triggered": False, "question": raw,
            "mode": "ask" if (marked and auto) else "suggest"}


def clip_answer(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return text


# Text the app or CLI prints when a turn did not actually produce an answer. Such
# a reply must never be cached as an "answer" (it would be served forever) nor
# notified as if it were the model's answer.
FAILURE_MARKERS = (
    "no reply:",
    "request was cancelled",
    "request was canceled",
    "stopped waiting for another hermes",
    "the turn stopped",
    "turn stopped",
)


def looks_like_failure(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(marker in low for marker in FAILURE_MARKERS)


def inline_text(answer: str) -> str:
    """Answer rendered into a KRunner ``multiline`` match (rich text, escaped)."""
    head = clip_answer(answer, 10_000)
    parts = []
    for line in head.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        # Escape first, then allow a small safe subset of markdown through as HTML.
        line = html_escape(line, quote=False)
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        if len(parts) >= 40:
            parts.append("…")
            break
        parts.append(line)
    return "<br>".join(parts) or html_escape(head or "", quote=False)


# ── cache ────────────────────────────────────────────────────────────────────
class AnswerCache:
    def __init__(self, path: Path, size: int):
        self.path = path
        self.size = max(1, int(size))
        self._lock = threading.Lock()
        self._entries: list = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            entries = data.get("entries") if isinstance(data, dict) else data
            if isinstance(entries, list):
                self._entries = [e for e in entries if isinstance(e, dict) and e.get("q") and e.get("a")]
        except (OSError, ValueError):
            self._entries = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"entries": self._entries[: self.size]}, ensure_ascii=False), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("cache write failed: %s", exc)

    def get(self, question: str):
        key = question_key(question)
        with self._lock:
            for entry in self._entries:
                if entry.get("k") == key:
                    entry["hits"] = int(entry.get("hits") or 0) + 1
                    return entry
        return None

    def put(self, question: str, answer: str, *, engine: str = "", session: str = "") -> None:
        if not answer:
            return
        key = question_key(question)
        entry = {
            "k": key, "q": question.strip(), "a": answer, "ts": time.time(),
            "engine": engine, "session": session,
        }
        with self._lock:
            self._entries = [e for e in self._entries if e.get("k") != key]
            self._entries.insert(0, entry)
            del self._entries[self.size:]
            self._save()

    def drop(self, question: str) -> None:
        key = question_key(question)
        with self._lock:
            self._entries = [e for e in self._entries if e.get("k") != key]
            self._save()


# ── desktop integration (clipboard / notification / app focus) ───────────────
def _run(cmd: list, timeout: float = 10, detached: bool = False) -> subprocess.CompletedProcess | None:
    try:
        if detached:
            subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, start_new_session=True)
            return None
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("command failed %s: %s", cmd[:2], exc)
        return None


def notify(summary: str, body: str = "", *, timeout_ms: int = 20000, urgency: str = "normal") -> None:
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send", "-a", "Hermes", "-i", "hermes", "-u", urgency, "-t", str(timeout_ms)]
    cmd += [summary]
    if body:
        cmd += [body]
    _run(cmd, timeout=5)


def hermes_bin(cfg: dict) -> str:
    explicit = str(cfg.get("hermes_bin") or "").strip()
    if explicit:
        return explicit
    found = shutil.which("hermes")
    if found:
        return found
    local = HOME / ".local/bin/hermes"
    return str(local) if local.exists() else "hermes"


FOCUS_SCRIPT = r"""
// Raise the Hermes desktop window (Plasma/KWin). Written by hermes-krunner.
function hermesWindows() {
    const wanted = HERMES_CLASSES;
    const found = [];
    const list = (typeof workspace.windowList === "function")
        ? workspace.windowList() : workspace.clientList();
    for (const w of list) {
        if (!w.normalWindow) continue;
        const cls = String(w.resourceClass || ""), nm = String(w.resourceName || "");
        if (wanted.indexOf(cls) >= 0 || wanted.indexOf(nm) >= 0) found.push(w);
    }
    return found;
}
const wins = hermesWindows();
if (wins.length > 0) {
    const w = wins[wins.length - 1];
    if (w.minimized) w.minimized = false;
    if (typeof workspace.raiseWindow === "function") workspace.raiseWindow(w);
    workspace.activeWindow = w;
    print("HERMES-KRUNNER focus -> " + w.resourceClass + " " + w.caption);
} else {
    print("HERMES-KRUNNER focus: no Hermes window found");
}
"""


def _window_classes(cfg: dict) -> list:
    raw = cfg.get("app_window_class") or "com.nousresearch.hermes"
    if isinstance(raw, str):
        raw = [raw]
    return [str(c) for c in raw] + ["Hermes", "hermes"]


def focus_app(cfg: dict) -> None:
    """Raise the running Hermes window (KWin script), else ask the app to focus
    itself by launching a second instance (Electron's single-instance lock)."""
    if focus_app_kwin(cfg):
        return
    _run([hermes_bin(cfg), "desktop", "--skip-build"], timeout=30, detached=True)


def focus_app_kwin(cfg: dict) -> bool:
    """Ask KWin to activate the Hermes window. Returns True when the raise was
    attempted (qdbus6 + KWin present)."""
    qdbus = next((b for b in ("qdbus6", "qdbus") if shutil.which(b)), None)
    if not qdbus:
        return False
    cache = Path(os.path.expanduser("~/.cache/hermes-krunner"))
    try:
        cache.mkdir(parents=True, exist_ok=True)
        script = cache / "focus-window.js"
        script.write_text(
            "const HERMES_CLASSES = %s;\n%s" % (json.dumps(_window_classes(cfg)), FOCUS_SCRIPT),
            encoding="utf-8")
    except OSError as exc:
        log.debug("could not write focus script: %s", exc)
        return False
    load = _run([qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
                 str(script)], timeout=10)
    started = _run([qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.start"], timeout=10)
    if started is None:
        return False  # no KWin on this session (e.g. not Plasma)
    log.debug("kwin focus script loaded=%s", load)
    try:  # keep KWin's script list clean
        if load is not None and str(load).strip().isdigit():
            threading.Timer(2.0, lambda: _run(
                [qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript",
                 str(load).strip()], timeout=10)).start()
    except Exception:  # noqa: BLE001
        pass
    return True


def launch_app(cfg: dict) -> None:
    log.info("launching Hermes desktop app")
    _run([hermes_bin(cfg), "desktop", "--skip-build"], timeout=60, detached=True)


# ── Hermes desktop backend (local JSON-RPC) ──────────────────────────────────
class BackendUnavailable(RuntimeError):
    pass


def find_serve_port() -> int | None:
    """Port of the ``hermes serve --host 127.0.0.1 --port 0`` process the desktop app spawns."""
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{entry}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if "serve" in cmd and "--port" in cmd and "hermes" in cmd:
            pids.append(entry)
    if not pids:
        return None
    ss = shutil.which("ss")
    if not ss:
        return None
    out = _run([ss, "-tlnpH"], timeout=5)
    if out is None:
        return None
    for line in out.stdout.splitlines():
        pid_match = re.search(r"pid=(\d+)", line)
        port_match = re.search(r"127\.0\.0\.1:(\d+)", line)
        if pid_match and port_match and pid_match.group(1) in pids:
            return int(port_match.group(1))
    return None


def fetch_token(port: int) -> str:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raise BackendUnavailable(f"backend on :{port} did not answer: {exc}") from exc
    m = re.search(r"__HERMES_SESSION_TOKEN__\s*=\s*\"([^\"]+)\"", html)
    return m.group(1) if m else ""


class AppBackend:
    """Tiny client for the desktop app's local JSON-RPC gateway."""

    def __init__(self, port: int | None = None):
        self.port = port or find_serve_port()
        self.token = ""
        self._rid = 0
        self._ws = None

    # -- connection ----------------------------------------------------------
    def connect(self, timeout: float = 10):
        if not self.port:
            raise BackendUnavailable("Hermes desktop backend is not running")
        try:
            from websockets.sync.client import connect as ws_connect
            from websockets.exceptions import WebSocketException
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailable("python3-websockets is not installed") from exc
        self.token = fetch_token(self.port)
        uri = f"ws://127.0.0.1:{self.port}/api/ws"
        if self.token:
            uri += f"?token={self.token}"
        try:
            self._ws = ws_connect(uri, open_timeout=timeout, close_timeout=3, max_size=None)
        except (OSError, WebSocketException) as exc:
            raise BackendUnavailable(f"websocket to :{self.port} failed: {exc}") from exc
        return self

    def close(self) -> None:
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._ws = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- rpc -----------------------------------------------------------------
    def rpc(self, method: str, params: dict | None = None, *, timeout: float = 60, backlog: list | None = None):
        if self._ws is None:
            self.connect()
        self._rid += 1
        mine = self._rid
        self._ws.send(json.dumps({"jsonrpc": "2.0", "id": mine, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"rpc {method} timed out")
            frame = json.loads(self._ws.recv(timeout=remaining))
            if frame.get("id") == mine and ("result" in frame or "error" in frame):
                if "error" in frame:
                    err = frame["error"] or {}
                    raise RuntimeError(f"{method}: {err.get('code')} {err.get('message')}")
                return frame.get("result") or {}
            if backlog is not None:
                backlog.append(frame)

    def sessions(self, limit: int = 200) -> list:
        res = self.rpc("session.list", {"limit": limit, "include_hidden": True}, timeout=30)
        return res.get("sessions") or res.get("rows") or []

    def find_session_by_title(self, title: str):
        want = normalize_text(title)
        for row in self.sessions():
            if normalize_text(str(row.get("title") or "")) == want:
                return row
        return None

    def ensure_session(self, title: str, *, rotate_after: int = 0) -> tuple:
        """Return ``(runtime_session_id, stored_session_id)`` for the quick-ask chat."""
        row = self.find_session_by_title(title)
        if row and not (rotate_after and int(row.get("message_count") or 0) >= rotate_after):
            res = self.rpc("session.resume", {"session_id": row["id"]}, timeout=60)
            sid = res.get("session_id") or row["id"]
            return sid, res.get("stored_session_id") or row["id"]
        res = self.rpc("session.create", {"cols": 96, "source": "desktop"}, timeout=60)
        sid = res.get("session_id")
        stored = res.get("stored_session_id") or sid
        try:
            self.rpc("session.title", {"session_id": sid, "title": title}, timeout=20)
        except RuntimeError as exc:
            log.debug("title set failed: %s", exc)
        return sid, stored

    def ask(self, question: str, *, session_title: str, rotate_after: int = 0,
            timeout: float = 240, on_submit=None) -> tuple:
        """Submit ``question`` and wait for the final answer.

        Returns ``(answer, stored_session_id)``.
        """
        sid, stored = self.ensure_session(session_title, rotate_after=rotate_after)
        backlog: list = []
        self.rpc("prompt.submit", {"session_id": sid, "text": question}, timeout=60, backlog=backlog)
        if on_submit:
            try:
                on_submit(stored)
            except Exception:  # noqa: BLE001
                log.debug("on_submit hook failed", exc_info=True)
        deadline = time.monotonic() + timeout
        answer = ""
        for frame in backlog:
            text = self._answer_from_frame(frame, sid)
            if text is not None:
                return text, stored
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "", stored
            try:
                frame = json.loads(self._ws.recv(timeout=remaining))
            except TimeoutError:
                return "", stored
            text = self._answer_from_frame(frame, sid)
            if text is not None:
                return text, stored
            err = ((frame.get("params") or {}).get("payload") or {}).get("error")
            if frame.get("method") == "event" and err and (frame.get("params") or {}).get("session_id") == sid:
                log.warning("turn error: %s", err)

    @staticmethod
    def _answer_from_frame(frame: dict, sid: str):
        if frame.get("method") != "event":
            return None
        params = frame.get("params") or {}
        if params.get("session_id") != sid:
            return None
        if params.get("type") == "message.complete":
            return str((params.get("payload") or {}).get("text") or "")
        return None


# ── headless CLI engine ──────────────────────────────────────────────────────
_BOX_CHARS = "─│╭╮╰╯━┃┏┓┗┛═║╔╗╚╝├┤┬┴┼"


def clean_cli_output(raw: str) -> str:
    lines = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if set(stripped) <= set(_BOX_CHARS + " "):
            continue
        lines.append(re.sub(rf"^[{_BOX_CHARS}\s]+|[{_BOX_CHARS}\s]+$", "", line).rstrip())
    return "\n".join(lines).strip()


class CliEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def ask(self, question: str, timeout: float = 240, session_title: str = "") -> tuple:
        cmd = [hermes_bin(self.cfg), "chat", "-q", question]
        cmd += [str(a) for a in (self.cfg.get("cli_extra_args") or ["--oneshot", "-Q"])]
        log.info("cli ask: %s", question[:80])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "", ""
        if proc.returncode != 0:
            log.warning("cli engine exit=%s stderr=%s", proc.returncode, (proc.stderr or "")[-300:])
        session = ""
        m = re.search(r"session_id:\s*(\S+)", proc.stderr or "")
        if m:
            session = m.group(1)
        return clean_cli_output(proc.stdout), session


# ── orchestration ────────────────────────────────────────────────────────────
class Ask:
    __slots__ = ("question", "started", "finished", "answer", "error", "engine", "session", "event")

    def __init__(self, question: str):
        self.question = question
        self.started = time.monotonic()
        self.finished: float | None = None
        self.answer = ""
        self.error = ""
        self.engine = ""
        self.session = ""
        self.event = threading.Event()

    @property
    def done(self) -> bool:
        return self.finished is not None

    def wait(self, timeout: float) -> str:
        self.event.wait(max(0.0, timeout))
        return self.answer


class Asker:
    """Owns engines, the answer cache, and in-flight questions."""

    def __init__(self, cfg: dict, cache: AnswerCache | None = None):
        self.cfg = cfg
        self.cache = cache if cache is not None else AnswerCache(CACHE_PATH, int(cfg.get("cache_size") or 120))
        self._lock = threading.Lock()
        self._inflight: dict = {}

    # -- engine selection ----------------------------------------------------
    def backend_up(self) -> bool:
        port = find_serve_port()
        if not port:
            return False
        try:
            fetch_token(port)
            return True
        except BackendUnavailable:
            return False

    def backend_ready(self, *, allow_launch: bool = True, timeout: float = 0) -> bool:
        if self.backend_up():
            return True
        if not allow_launch or not self.cfg.get("launch_app_if_down"):
            return False
        launch_app(self.cfg)
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            time.sleep(1.0)
            if self.backend_up():
                return True
        return False

    def ask_via_app(self, question: str, *, timeout: float, session_title: str | None = None) -> tuple:
        title = session_title or str(self.cfg.get("session_title") or "پرسش سریع")
        with AppBackend() as backend:
            return backend.ask(
                question, session_title=title, timeout=timeout,
                rotate_after=int(self.cfg.get("session_rotate_after_messages") or 0),
            )

    def launch_app_soon(self, delay: float = 2.0) -> None:
        """Bring the desktop app up without blocking (or stealing) the current ask."""
        if not self.cfg.get("launch_app_if_down"):
            return

        def worker():
            time.sleep(max(0.0, delay))
            launch_app(self.cfg)

        threading.Thread(target=worker, name="hermes-launch-app", daemon=True).start()

    # -- asking --------------------------------------------------------------
    def start(self, question: str, *, force: bool = False, new_session: bool = False,
              notify_when_done: bool = True) -> Ask:
        key = question_key(question)
        if not force:
            cached = self.cache.get(question)
            if cached:
                ask = Ask(question)
                ask.answer = cached.get("a") or ""
                ask.engine = "cache"
                ask.session = cached.get("session") or ""
                ask.finished = time.monotonic()
                ask.event.set()
                return ask
            with self._lock:
                running = self._inflight.get(key)
            if running is not None and not running.done:
                return running
        with self._lock:
            ask = self._inflight.get(key)
            if ask is not None and not ask.done and not force and not new_session:
                return ask
            ask = Ask(question)
            self._inflight[key] = ask
        threading.Thread(
            target=self._run_ask, args=(ask, force, new_session, notify_when_done),
            name="hermes-ask", daemon=True).start()
        return ask

    def _run_ask(self, ask: Ask, force: bool, new_session: bool, notify_when_done: bool) -> None:
        cfg = self.cfg
        engine_pref = str(cfg.get("engine") or "auto").lower()
        started = time.monotonic()
        try:
            app_up = self.backend_up()
            if engine_pref in ("auto", "app") and not app_up and engine_pref == "app":
                # Strict app mode: wait for the app to come up before giving up.
                app_up = self.backend_ready(timeout=float(cfg.get("app_start_timeout_s") or 60))
            elif engine_pref in ("auto", "app") and not app_up:
                # App is down: bring it up in the background, answer through the CLI
                # engine in the meantime so KRunner still gets an inline answer.
                self.launch_app_soon()
            if app_up:
                try:
                    answer, stored = self.ask_via_app(
                        ask.question,
                        timeout=float(cfg.get("answer_timeout_s") or 240),
                        session_title=None if not new_session else self._fresh_title(),
                    )
                    if answer:
                        ask.answer = answer
                        ask.engine = "app"
                        ask.session = stored
                except (BackendUnavailable, RuntimeError, TimeoutError, OSError) as exc:
                    log.warning("app engine failed: %s", exc)
            if ask.answer and looks_like_failure(ask.answer):
                # e.g. "⚠️ No reply: the request was cancelled…" — report it as an
                # error and let the other engine have a go.
                log.info("engine %s returned a failure text, not an answer", ask.engine or "app")
                ask.error = clip_answer(ask.answer, 300)
                ask.answer = ""
            if not ask.answer and engine_pref in ("auto", "cli"):
                answer, session = CliEngine(cfg).ask(
                    ask.question, timeout=float(cfg.get("answer_timeout_s") or 240))
                if answer:
                    ask.answer = answer
                    ask.engine = "cli"
                    ask.session = session
            if not ask.answer and not ask.error:
                ask.error = "no answer"
        except Exception as exc:  # noqa: BLE001 — a runner must never die on one bad ask
            log.exception("ask failed")
            ask.error = str(exc)
        finally:
            ask.finished = time.monotonic()
            ask.event.set()
            log.info(
                "ask done engine=%s %.1fs chars=%d q=%r",
                ask.engine or ask.error, ask.finished - started, len(ask.answer), ask.question[:70])
            if ask.answer:
                self.cache.put(ask.question, ask.answer, engine=ask.engine, session=ask.session)
                if notify_when_done and cfg.get("notify"):
                    self._notify_answer(ask)

    def _fresh_title(self) -> str:
        return f"{self.cfg.get('session_title') or 'پرسش سریع'} · {time.strftime('%H:%M')}"

    def _notify_answer(self, ask: Ask) -> None:
        body = clip_answer(ask.answer, 600)
        source = {"app": "از برنامه هرمس", "cli": "از موتور خط فرمان"}.get(ask.engine, ask.engine)
        notify(f"هرمس: {clip_answer(ask.question, 70)}", f"{body}\n({source})", timeout_ms=25000)

    def open_in_app(self, question: str) -> None:
        """The default action: make sure the question reached the app, then raise its window."""
        try:
            if self.backend_up():
                # Already asked during Match (or ask it now) — the chat is in the app.
                self.start(question, notify_when_done=False)
            else:
                self.launch_app_soon(delay=0.0)
        except Exception:  # noqa: BLE001
            log.debug("open_in_app could not submit", exc_info=True)
        focus_app(self.cfg)

    def answer_now(self, question: str, *, timeout: float, force: bool = False) -> tuple:
        """Return ``(answer, ask)``; the ask keeps running if the timeout hits."""
        ask = self.start(question, force=force)
        if ask.done:
            return ask.answer, ask
        return ask.wait(timeout), ask


# ── match construction (pure-ish) ────────────────────────────────────────────
ACTION_OPEN = "open"
ACTION_REASK = "reask"
ACTION_NEW = "new"

ACTIONS = [
    (ACTION_OPEN, "باز کردن در هرمس", "hermes"),
    (ACTION_REASK, "دوباره بپرس", "view-refresh"),
    (ACTION_NEW, "در گفتگوی تازه بپرس", "list-add"),
]


def _dbus_types():
    """dbus-python types when available (they are plain int/str/float/dict subclasses)."""
    try:
        import dbus  # noqa: PLC0415
        return dbus
    except ImportError:
        return None


def build_match(match_id: str, text: str, *, icon: str = "hermes", relevance: float = 0.9,
                category_relevance: int = 70, subtext: str = "", multiline: bool = False,
                actions: list | None = None, urls: list | None = None) -> tuple:
    """One ``RemoteMatch`` tuple: (id, text, icon, categoryRelevance, relevance, properties).

    Values are wrapped in dbus types so an empty list inside the ``a{sv}`` map still
    carries a signature (dbus-python cannot guess one for a bare ``[]``).
    """
    dbus = _dbus_types()
    strs = dbus.Array(list(actions or []), signature="s") if dbus else list(actions or [])
    props: dict = {}
    if subtext:
        props["subtext"] = dbus.String(subtext) if dbus else subtext
    props["category"] = dbus.String("هرمس") if dbus else "هرمس"
    if multiline:
        props["multiline"] = dbus.Boolean(True) if dbus else True
    if urls:
        props["urls"] = dbus.Array(list(urls), signature="s") if dbus else list(urls)
    props["actions"] = strs
    if dbus:
        props = dbus.Dictionary(props, signature="sv")
        return (dbus.String(match_id), dbus.String(text), dbus.String(icon),
                dbus.Int32(int(category_relevance)), dbus.Double(float(relevance)), props)
    return (match_id, text, icon, int(category_relevance), float(relevance), props)


def empty_matches():
    dbus = _dbus_types()
    return dbus.Array([], signature="(sssida{sv})") if dbus else []


# ── D-Bus service ────────────────────────────────────────────────────────────
class ServiceState:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.asker = Asker(cfg)
        self.lock = threading.Lock()
        self.last_query = time.monotonic()
        self.seq = 0
        self.current_question = ""
        self.activation_token = ""
        self.loop = None


def _dbus_prepare():
    import dbus
    import dbus.mainloop.glib
    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    return dbus, GLib


def serve(cfg: dict) -> int:
    dbus, GLib = _dbus_prepare()
    import dbus.lowlevel
    import dbus.service

    state = ServiceState(cfg)
    session_bus = dbus.SessionBus()

    def reply(conn, call, args=None, signature: str | None = None) -> None:
        msg = dbus.lowlevel.MethodReturnMessage(call)
        if args is not None:
            msg.append(args, signature=signature) if signature else msg.append(args)
        conn.send_message(msg)

    def reply_error(conn, call, name: str, text: str) -> None:
        msg = dbus.lowlevel.ErrorMessage(call, name, text)
        conn.send_message(msg)

    # -- method handlers -----------------------------------------------------
    def answer_match(question: str, text: str, sub: str, *, relevance: float, pending: bool = False):
        return build_match(
            f"ask::{question}", text,
            relevance=relevance,
            category_relevance=int(cfg.get("answer_category_relevance") if not pending
                                   else cfg.get("hint_category_relevance") or 70),
            subtext=sub, multiline=True,
            actions=[ACTION_OPEN, ACTION_REASK, ACTION_NEW])

    def do_match(conn, call, query: str) -> None:
        state.last_query = time.monotonic()
        decision = classify_query(cfg, query)
        mode, question = decision["mode"], decision["question"]
        log.info("Match q=%r mode=%s question=%r", decision["raw"][:80], mode, question[:80])

        if mode == "ignore":
            reply(conn, call, empty_matches(), "a(sssida{sv})")
            return
        if mode == "hint":
            matches = [build_match(
                "hint", "از هرمس بپرس — سؤالت را بعد از نشانه بنویس",
                relevance=0.5, category_relevance=int(cfg.get("hint_category_relevance") or 70),
                subtext=f"مثال: {(cfg.get('triggers') or ['?'])[0]} پایتخت استرالیا کجاست؟",
                actions=[ACTION_OPEN])] if cfg.get("show_hint_when_empty", True) else []
            reply(conn, call, matches, "a(sssida{sv})")
            return

        cached = state.asker.cache.get(question)
        if cached:
            answer = cached.get("a") or ""
            matches = [answer_match(
                question,
                inline_text(clip_answer(answer, int(cfg.get("inline_answer_chars") or 1500))),
                "از حافظه · Enter: باز کردن در هرمس", relevance=1.0)]
            reply(conn, call, matches, "a(sssida{sv})")
            return

        if mode in ("suggest", "manual"):
            # Suggestion only: no model call until the row is activated.
            matches = [build_match(
                f"ask::{question}", f"از هرمس بپرس: {question}",
                relevance=float(cfg.get("suggest_relevance") or 0.5),
                category_relevance=int(cfg.get("suggest_category_relevance") or 50),
                subtext="Enter: پرسیدن و رفتن به هرمس", actions=[ACTION_OPEN, ACTION_NEW])]
            reply(conn, call, matches, "a(sssida{sv})")
            return

        # mode == "ask": KRunner calls Match on every keystroke, so:
        #  1. debounce — wait for the query to settle; a newer Match supersedes this one;
        #  2. only the settled (newest) query actually asks Hermes;
        #  3. hold that reply until the answer arrives (KRunner shows it inline).
        with state.lock:
            state.seq += 1
            my_seq = state.seq
        if cfg.get("auto_ask", True):
            settle_until = time.monotonic() + max(0.0, float(cfg.get("debounce_ms") or 700) / 1000.0)
            while time.monotonic() < settle_until:
                time.sleep(0.05)
                with state.lock:
                    if state.seq != my_seq:
                        break
            with state.lock:
                superseded = state.seq != my_seq
            if superseded:
                # A newer keystroke is already being handled — answer this one instantly.
                reply(conn, call, [answer_match(
                    question, f"از هرمس می‌پرسم: {question}", "چند لحظه…",
                    relevance=0.4, pending=True)], "a(sssida{sv})")
                return

        ask = state.asker.start(question)
        with state.lock:
            state.current_question = question
        wait_s = float(cfg.get("inline_wait_s") or 18)
        if not state.asker.backend_up() and not ask.done:
            wait_s = 0.0
        if cfg.get("auto_ask", True) and wait_s > 0 and not ask.done:
            ask.event.wait(wait_s)
        pending = not ask.done
        if not cfg.get("auto_ask", True) and not ask.done:
            text = f"از هرمس بپرس: {question}"
            sub = "Enter: پرسیدن و رفتن به هرمس"
        elif pending:
            text = f"از هرمس می‌پرسم: {question}"
            sub = "هرمس دارد فکر می‌کند… (پاسخ در نوتیفیکیشن می‌آید، و با یک تایپ دوباره این‌جا)"
        elif ask.answer:
            text = inline_text(clip_answer(ask.answer, int(cfg.get("inline_answer_chars") or 1500)))
            sub = f"Enter: باز کردن در هرمس · {'حافظه' if ask.engine == 'cache' else ask.engine}"
        else:
            text = f"هرمس جوابی نداد: {question}"
            sub = ask.error or "خطای نامشخص"
        matches = [answer_match(question, text, sub,
                                relevance=1.0 if not pending else 0.6, pending=pending)]
        if not pending and ask.answer and cfg.get("notify_inline_answers") and cfg.get("notify"):
            state.asker._notify_answer(ask)
        reply(conn, call, matches, "a(sssida{sv})")

    def do_run(conn, call, match_id: str, action_id: str) -> None:
        state.last_query = time.monotonic()
        log.info("Run id=%r action=%r", match_id, action_id)
        if match_id.startswith("ask::"):
            question = match_id[len("ask::"):]
            action = action_id or ACTION_OPEN  # Enter = go to Hermes
            if action in ("", ACTION_OPEN):
                state.asker.open_in_app(question)
            elif action == ACTION_NEW:
                state.asker.start(question, force=True, new_session=True)
                focus_app(cfg)
            elif action == ACTION_REASK:
                state.asker.start(question, force=True)
        elif match_id == "hint":
            focus_app(cfg)
        reply(conn, call, None)

    def do_actions(conn, call) -> None:
        reply(conn, call, [(a[0], a[1], a[2]) for a in ACTIONS], "a(sss)")

    def do_config(conn, call) -> None:
        min_letters = max(1, min(len(str(t)) for t in (cfg.get("triggers") or ["?"])))
        reply(conn, call, {"MinLetterCount": dbus.Int32(min_letters)}, "a{sv}")

    def do_teardown(conn, call) -> None:
        with state.lock:
            state.current_question = ""
        reply(conn, call, None)

    def do_token(conn, call, token: str) -> None:
        state.activation_token = token
        reply(conn, call, None)

    # -- message filter ------------------------------------------------------
    def on_message(conn, message):
        if not isinstance(message, dbus.lowlevel.MethodCallMessage):
            return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED
        if message.get_path() != OBJECT_PATH:
            return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED
        iface = message.get_interface()
        if iface not in (None, IFACE):
            return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED
        member = message.get_member()
        args = message.get_args_list()
        conn = session_bus

        def guard(fn, *a):
            def run():
                try:
                    fn(conn, message, *a)
                except Exception:  # noqa: BLE001
                    log.exception("handler %s failed", member)
                    try:
                        reply_error(conn, message, "org.kde.krunner1.Error", "internal error")
                    except Exception:  # noqa: BLE001
                        pass
            return run

        handlers = {
            "Match": (do_match, tuple(args[:1])),
            "Run": (do_run, tuple(args[:2])),
            "Actions": (do_actions, ()),
            "Config": (do_config, ()),
            "Teardown": (do_teardown, ()),
            "SetActivationToken": (do_token, tuple(args[:1])),
        }
        if member in handlers:
            fn, extra = handlers[member]
            threading.Thread(target=guard(fn, *extra), name=f"dbus-{member}", daemon=True).start()
        else:
            return dbus.lowlevel.HANDLER_RESULT_NOT_YET_HANDLED
        return dbus.lowlevel.HANDLER_RESULT_HANDLED

    session_bus.add_message_filter(on_message)
    bus_name = dbus.service.BusName(BUS_NAME, session_bus)
    log.info("serving %s at %s (pid %d)", BUS_NAME, OBJECT_PATH, os.getpid())
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    loop = GLib.MainLoop()
    state.loop = loop

    def on_term(*_a):
        log.info("signal — quitting")
        loop.quit()
        return False

    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, on_term)

    idle_min = float(cfg.get("idle_exit_minutes") or 0)

    def idle_check():
        if idle_min and (time.monotonic() - state.last_query) > idle_min * 60:
            log.info("idle for %.0f min — exiting", idle_min)
            loop.quit()
            return False
        return True

    if idle_min:
        GLib.timeout_add_seconds(60, idle_check)
    try:
        loop.run()
    finally:
        try:
            PID_PATH.unlink()
        except OSError:
            pass
        try:
            del bus_name
        except Exception:  # noqa: BLE001
            pass
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def cmd_ask(cfg: dict, question: str, *, force: bool, new_session: bool) -> int:
    asker = Asker(cfg)
    if asker.cfg.get("launch_app_if_down") and not asker.backend_up():
        asker.backend_ready(timeout=float(cfg.get("app_start_timeout_s") or 60))
    ask = asker.start(question, force=force, new_session=new_session, notify_when_done=False)
    ask.event.wait(float(cfg.get("answer_timeout_s") or 240))
    if ask.answer:
        print(ask.answer)
        return 0
    print(f"[no answer] engine={ask.engine} error={ask.error}", file=sys.stderr)
    return 1


def cmd_match(cfg: dict, query: str) -> int:
    is_ask, question = strip_trigger(query, cfg.get("triggers") or [])
    if not is_ask:
        print(json.dumps({"is_ask": False, "matches": []}, ensure_ascii=False))
        return 0
    if not question:
        print(json.dumps({"is_ask": True, "question": "", "matches": ["(hint)"]}, ensure_ascii=False))
        return 0
    asker = Asker(cfg)
    ask = asker.start(question)
    ask.event.wait(float(cfg.get("inline_wait_s") or 18))
    print(json.dumps({
        "is_ask": True, "question": question, "pending": not ask.done,
        "engine": ask.engine, "session": ask.session,
        "answer": clip_answer(ask.answer, 2000),
    }, ensure_ascii=False, indent=2))
    return 0 if ask.answer else 1


def cmd_status(cfg: dict) -> int:
    port = find_serve_port()
    up = False
    if port:
        try:
            fetch_token(port)
            up = True
        except BackendUnavailable:
            up = False
    info = {
        "config": str(CONFIG_PATH),
        "state_dir": str(STATE_DIR),
        "triggers": cfg.get("triggers"),
        "engine": cfg.get("engine"),
        "desktop_backend": {"port": port, "reachable": up},
        "app_running": bool(up),
        "hermes_bin": hermes_bin(cfg),
        "launch_app_if_down": cfg.get("launch_app_if_down"),
        "websockets": _module_available("websockets"),
        "dbus": _module_available("dbus"),
        "service_pid": _read_pid(),
        "session_title": cfg.get("session_title"),
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def _module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def _read_pid():
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def cmd_stop(cfg: dict) -> int:
    pid = _read_pid()
    if not pid:
        print("no running hermes-krunner service")
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"could not stop pid {pid}: {exc}")
        return 1
    print(f"stopped pid {pid}")
    return 0


def cmd_clear_cache(cfg: dict) -> int:
    cache = AnswerCache(CACHE_PATH, int(cfg.get("cache_size") or 120))
    count = len(cache._entries)
    cache._entries = []
    cache._save()
    print(f"cache cleared ({count} entries): {CACHE_PATH}")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask Hermes from KRunner (Alt+F2)")
    parser.add_argument("--ask", metavar="QUESTION", help="ask once and print the answer")
    parser.add_argument("--match", metavar="QUERY", help="print the matches KRunner would receive")
    parser.add_argument("--status", action="store_true", help="show backend/app status")
    parser.add_argument("--stop", action="store_true", help="stop the running service")
    parser.add_argument("--clear-cache", action="store_true", help="drop the cached answers")
    parser.add_argument("--force", action="store_true", help="bypass the answer cache")
    parser.add_argument("--new-session", action="store_true", help="ask in a fresh chat")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    cfg = load_config()
    setup_logging(args.log_level or cfg.get("log_level") or "INFO", to_stderr=bool(args.ask or args.match or args.status))

    if args.status:
        return cmd_status(cfg)
    if args.stop:
        return cmd_stop(cfg)
    if args.clear_cache:
        return cmd_clear_cache(cfg)
    if args.ask:
        return cmd_ask(cfg, args.ask, force=args.force, new_session=args.new_session)
    if args.match:
        return cmd_match(cfg, args.match)
    return serve(cfg)


if __name__ == "__main__":
    sys.exit(main())
