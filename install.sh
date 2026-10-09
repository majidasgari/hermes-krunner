#!/usr/bin/env bash
# hرمس در KRunner — نصب پلاگین
#   ./install.sh            نصب (و ری‌استارت KRunner)
#   ./install.sh --no-restart
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_PY="$REPO_DIR/hermes-krunner.py"
BUS_NAME="org.maxv.hermeskrunner"

# The runner needs dbus-python, PyGObject and websockets. A Hermes-managed venv
# python (often first on PATH inside a Hermes session) has none of them, so probe
# candidates and take the first one that can actually serve KRunner.
pick_python() {
  local cand
  for cand in /usr/bin/python3 "$(command -v python3 2>/dev/null)" /usr/bin/python3.13 /usr/bin/python3.12 /usr/bin/python3.11; do
    [[ -n "$cand" && -x "$cand" ]] || continue
    if "$cand" - <<'PYCHK' >/dev/null 2>&1
import importlib.util, sys
sys.exit(0 if all(importlib.util.find_spec(m) for m in ("dbus", "gi", "websockets")) else 1)
PYCHK
    then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

PY="$(pick_python)" || {
  echo "!! هیچ پایتونی با dbus + gi + websockets پیدا نشد."
  echo "   نصب: sudo apt install python3-dbus python3-gi python3-websockets"
  exit 1
}

RUNNER_DIR="$HOME/.local/share/krunner/dbusplugins"
DBUS_DIR="$HOME/.local/share/dbus-1/services"
CONFIG_DIR="$HOME/.config/hermes-krunner"
KRUNNERRC="$HOME/.config/krunnerrc"

RESTART=1
[[ "${1:-}" == "--no-restart" ]] && RESTART=0

echo "== hermes-krunner install =="
echo "python: $PY"
command -v "$PY" >/dev/null || { echo "python3 not found"; exit 1; }
"$PY" - <<'PYCHECK' || echo "!! missing python modules — install python3-dbus, python3-gi, python3-websockets"
import importlib.util, sys
missing = [m for m in ("dbus", "gi", "websockets") if importlib.util.find_spec(m) is None]
print("python modules:", "missing " + ", ".join(missing) if missing else "ok")
sys.exit(1 if missing else 0)
PYCHECK

mkdir -p "$RUNNER_DIR" "$DBUS_DIR" "$CONFIG_DIR"

# 1. runner metadata for KRunner
sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/xdg/hermes-krunner.desktop" > "$RUNNER_DIR/hermes-krunner.desktop"

# 2. D-Bus activation: KRunner's first call starts the runner, no autostart needed
cat > "$DBUS_DIR/${BUS_NAME}.service" <<EOF
[D-BUS Service]
Name=${BUS_NAME}
Exec=${PY} ${RUNNER_PY}
EOF

# 3. config (kept if it already exists — edit freely)
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  cp "$REPO_DIR/config.example.json" "$CONFIG_DIR/config.json"
  echo "config: $CONFIG_DIR/config.json (defaults)"
else
  echo "config: $CONFIG_DIR/config.json (kept)"
fi

# 4. enable the runner in krunnerrc (KRunner usually enables new DBus runners itself)
if [[ -f "$KRUNNERRC" ]] && ! grep -q "^hermes-krunnerEnabled=" "$KRUNNERRC"; then
  if grep -q "^\[Plugins\]" "$KRUNNERRC"; then
    python3 - "$KRUNNERRC" <<'PYRC'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
lines = p.read_text(encoding="utf-8").splitlines()
out, done = [], False
for line in lines:
    out.append(line)
    if line.strip() == "[Plugins]" and not done:
        out.append("hermes-krunnerEnabled=true")
        done = True
if not done:
    out += ["", "[Plugins]", "hermes-krunnerEnabled=true"]
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PYRC
    echo "krunnerrc: enabled hermes-krunner"
  else
    printf '\n[Plugins]\nhermes-krunnerEnabled=true\n' >> "$KRUNNERRC"
    echo "krunnerrc: enabled hermes-krunner"
  fi
fi

# 5. stale service from a previous install
"$PY" "$RUNNER_PY" --stop >/dev/null 2>&1 || true

# 6. restart KRunner so it rescans ~/.local/share/krunner/dbusplugins
restart_krunner() {
  if command -v kquitapp6 >/dev/null; then
    kquitapp6 krunner >/dev/null 2>&1 || true
    sleep 1
    # org.kde.krunner is a D-Bus-activated service (SystemdService=plasma-krunner.service),
    # so a plain ping brings a fresh instance up with the new plugin list.
    dbus-send --session --print-reply --dest=org.kde.krunner / org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1 || true
  elif systemctl --user restart plasma-krunner.service 2>/dev/null; then
    :
  fi
}

if [[ "$RESTART" == "1" ]]; then
  restart_krunner
fi

echo
echo "نصب شد. تست:"
echo "  $PY $RUNNER_PY --status"
echo "  $PY $RUNNER_PY --match '? پایتخت استرالیا کجاست؟'"
echo "سپس در KRunner (Alt+F2) بنویس:  ? سؤالت"
