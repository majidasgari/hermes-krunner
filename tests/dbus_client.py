#!/usr/bin/env python3
"""End-to-end client for the running hermes-krunner D-Bus service.

This is exactly what KRunner does: activate the service, then call
Match / Actions / Config / Run over the session bus.

Usage:
  python3 tests/dbus_client.py "? رنگ آسمان چیست؟"
  python3 tests/dbus_client.py --actions
  python3 tests/dbus_client.py --config
  python3 tests/dbus_client.py --run "ask::رنگ آسمان" copy
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import dbus

BUS = os.environ.get("HERMES_KRUNNER_BUS") or "org.maxv.hermeskrunner"
PATH = os.environ.get("HERMES_KRUNNER_OBJECT") or "/runner"


def describe(matches) -> None:
    if not matches:
        print("matches: (none)")
        return
    for m in matches:
        mid, text, icon, cat, rel, props = m
        props = {str(k): v for k, v in dict(props).items()}
        plain = props.get("subtext", "")
        print(f"matches: id={mid!r} rel={float(rel):.2f} category_rel={int(cat)} icon={icon}")
        print(f"         text={str(text)[:200]!r}")
        if plain:
            print(f"         subtext={str(plain)!r}")
        print(f"         props={sorted(props)} multiline={bool(props.get('multiline', False))} "
              f"actions={[str(a) for a in props.get('actions', [])]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="KRunner query, e.g. '? پایتخت استرالیا'")
    ap.add_argument("--actions", action="store_true")
    ap.add_argument("--config", action="store_true")
    ap.add_argument("--run", nargs=2, metavar=("MATCH_ID", "ACTION_ID"))
    ap.add_argument("--wait", type=float, default=30.0, help="D-Bus reply timeout")
    ap.add_argument("--introspect", action="store_true")
    args = ap.parse_args()

    bus = dbus.SessionBus()
    iface = dbus.Interface(bus.get_object(BUS, PATH), "org.kde.krunner1")

    started = time.monotonic()
    try:
        if args.introspect:
            print(bus.get_object(BUS, PATH).Introspect(dbus_interface="org.freedesktop.DBus.Introspectable"))
            return 0
        if args.actions:
            print("actions:", [tuple(str(x) for x in a) for a in iface.Actions(timeout=args.wait)])
            return 0
        if args.config:
            print("config:", {str(k): v for k, v in dict(iface.Config(timeout=args.wait)).items()})
            return 0
        if args.run:
            iface.Run(args.run[0], args.run[1], timeout=args.wait)
            print(f"Run({args.run[0]}, {args.run[1]}) ok in {time.monotonic() - started:.1f}s")
            return 0
        if not args.query:
            ap.error("need a query, or --actions/--config/--run")
        print(f"Match({args.query!r}) …")
        matches = iface.Match(args.query, timeout=args.wait)
        print(f"replied in {time.monotonic() - started:.1f}s")
        describe(matches)
        return 0
    except dbus.exceptions.DBusException as exc:
        print(f"D-Bus error: {exc.get_dbus_name()}: {exc.get_dbus_message()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
