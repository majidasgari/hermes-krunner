#!/usr/bin/env bash
# حذف پلاگین هرمس از KRunner
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUS_NAME="org.maxv.hermeskrunner"

echo "== hermes-krunner uninstall =="
python3 "$REPO_DIR/hermes-krunner.py" --stop >/dev/null 2>&1 || true
rm -f "$HOME/.local/share/krunner/dbusplugins/hermes-krunner.desktop"
rm -f "$HOME/.local/share/dbus-1/services/${BUS_NAME}.service"

# disable in krunnerrc
python3 - <<'PYRC' || true
import pathlib
p = pathlib.Path.home() / ".config/krunnerrc"
if p.exists():
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("hermes-krunnerEnabled=")]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
PYRC

if command -v kquitapp6 >/dev/null; then
  kquitapp6 krunner >/dev/null 2>&1 || true
  sleep 1
  dbus-send --session --print-reply --dest=org.kde.krunner / org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1 || true
fi

echo "حذف شد. (config و کش دست‌نخورده ماندند: ~/.config/hermes-krunner، ~/.cache/hermes-krunner)"
