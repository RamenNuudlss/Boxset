"""Boxset: turn movie rips into a Blu-ray with a themed menu.

  boxset                            open the app
  boxset-cli check   <project>      read every rip and show the disc-space plan
  boxset-cli themes  <project>      list available themes
  boxset-cli menus   <project>      render every menu screen (and check them)
  boxset-cli preview <project>      save a contact sheet of the screens
  boxset-cli build   <project>      encode films and write the disc folder (--iso for an image)

<project> is a .boxset file made in the app. From source, use `python -m boxset`.
"""
from __future__ import annotations

import argparse
import sys
import time

from . import budget, config, core, pipeline, probe
from .config import ConfigError


def say(msg=""):
    print(msg, flush=True)


class Printer:
    """Turns pipeline events into terminal output."""

    def __init__(self):
        self.last = 0.0

    def __call__(self, e):
        t = e["type"]
        if t == "stage" and e["status"] in ("start", "skipped", "done") and e.get("label"):
            say(("  " if e["status"] == "done" else "") + e["label"])
        elif t == "log":
            say(f"  {'note: ' if e['level'] == 'warn' else ''}{e['message']}")
        elif t == "film" and e["status"] == "encoding":
            say(f"  Film {e['film']:02d}: {e['title']}")
        elif t == "progress" and e["stage"] == "encode" and time.time() - self.last > 30:
            self.last = time.time()
            eta = f", about {int(e['eta'] // 60)} min left" if e.get("eta") else ""
            say(f"    {e['pct'] * 100:4.1f}% at {e['speed']}x{eta}")


def cmd_check(args):
    coll = config.load(args.collection)
    say(f"Reading {len(coll.films)} rips…\n")
    media, problems = pipeline.load_media(coll, refresh=args.refresh)
    for film in coll.films:
        m = media.get(film.number)
        if not m:
            say(f"  {film.number:02d}  {film.title:<40}  could not read")
            continue
        langs = ", ".join(f"{a.codec} {a.channels}ch {a.language}" for a in m.audio[:2])
        say(f"  {film.number:02d}  {film.title[:40]:<40}  {probe.timecode(m.duration):>8}  "
            f"{m.width}x{m.height} {m.fps_label}fps  {len(m.chapters):>2} ch  {langs}")
    say()
    if len(media) == len(coll.films):
        say(budget.plan(coll.disc_size, [m.duration for m in media.values()], coll.audio_kbps).describe())
    notes = [(f.number, p) for f in coll.films if f.number in media for p in media[f.number].problems]
    if notes:
        say("\nGood to know:")
        for n, p in notes:
            say(f"  - Film {n}: {p}")
    if problems:
        say("\nThings to fix:")
        for n, p in problems:
            say(f"  - Film {n}: {p}")
        return 1
    say("\nEverything looks good. Next: boxset-cli menus")
    return 0


def cmd_themes(args):
    coll = config.load(args.collection)
    for name in core.list_themes(coll):
        theme, _ = core.load_theme(coll, name, {})
        say(f" {'*' if name == coll.theme else ' '} {name:<16} {theme.description}")
    return 0


def _run(args, **kw):
    job = pipeline.Job(Printer())
    try:
        return job, pipeline.run(args.collection, job, **kw)
    except pipeline.Cancelled:
        say("Stopped.")
        return job, None


def cmd_menus(args):
    if args.theme:
        # try a theme without editing the project file
        import json, os, tempfile
        with open(args.collection, encoding="utf-8") as fh:
            data = json.load(fh)
        data["theme"] = args.theme
        tmp = os.path.join(os.path.dirname(os.path.abspath(args.collection)), ".boxset-theme-try.json")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        args.collection = tmp
    _, res = _run(args, menus_only=True, force_menus=args.force)
    if res:
        say("All Blu-ray checks passed. Next: boxset-cli preview (optional), then boxset-cli build")
    return 0 if res else 1


def cmd_preview(args):
    from .preview import contact_sheet
    say(f"Saved {contact_sheet(config.load(args.collection).build)}")
    return 0


def cmd_build(args):
    _, res = _run(args, skip_encode=args.skip_encode, fast=args.fast, make_iso=args.iso)
    if not res:
        return 1
    say(f"\nDisc ready: {res['titles']} films, {res['menus']} menus, {res['chapters']} chapters, "
        f"{res['bytes'] / 1e9:.2f} GB\n  {res['folder']}")
    if res.get("iso"):
        say(f"  {res['iso']}")
    return 0


def cmd_gui(args):
    from .gui.app import main as gui_main
    return gui_main(args.collection, browser=args.browser)


def main(argv=None):
    from . import winfix
    winfix.apply()
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in {"check", "themes", "menus", "preview", "build", "gui", "-h", "--help"}:
        argv = ["gui"] + argv
    ap = argparse.ArgumentParser(prog="boxset", description="Build a Blu-ray collection disc with a themed menu.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, helptext in [
        ("gui", cmd_gui, "open the app"),
        ("check", cmd_check, "read every rip and show the disc-space plan"),
        ("themes", cmd_themes, "list the themes you can use"),
        ("menus", cmd_menus, "render every menu screen"),
        ("preview", cmd_preview, "save a contact sheet of the rendered screens"),
        ("build", cmd_build, "encode films and write the disc"),
    ]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("collection", nargs="?" if name == "gui" else None, default=None,
                        metavar="project", help="a .boxset project file")
        sp.set_defaults(fn=fn)
        if name == "gui":
            sp.add_argument("--browser", action="store_true", help="open in a web browser instead of a window")
        if name == "check":
            sp.add_argument("--refresh", action="store_true", help="re-read every file instead of using the cache")
        if name == "menus":
            sp.add_argument("--theme", help="try this theme without changing the project")
            sp.add_argument("--force", action="store_true", help="re-render even if nothing changed")
        if name == "build":
            sp.add_argument("--skip-encode", action="store_true", help="reuse already-encoded films")
            sp.add_argument("--fast", action="store_true", help="quick low-quality encodes, for testing")
            sp.add_argument("--iso", action="store_true", help="also make a disc image (Windows)")
    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except ConfigError as e:
        say(f"Project problem: {e}")
        return 2
    except RuntimeError as e:
        say(f"Error: {e}")
        return 3
    except KeyboardInterrupt:
        say("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
