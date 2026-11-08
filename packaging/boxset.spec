# PyInstaller spec for Boxset (Windows).  Build with:  pyinstaller packaging/boxset.spec
# Produces dist/Boxset/ with Boxset.exe (the app, no console) and boxset-cli.exe
# (same program with a console, for the command line). FFmpeg goes in dist/Boxset/bin.
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hidden = [], [], []
for pkg in ("playwright", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
datas += [
    (os.path.join(ROOT, "boxset", "fonts"), os.path.join("boxset", "fonts")),
    (os.path.join(ROOT, "boxset", "themes"), os.path.join("boxset", "themes")),
    (os.path.join(ROOT, "boxset", "gui", "web"), os.path.join("boxset", "gui", "web")),
]
hidden += ["bdmvkit", "bdmvkit.encode", "bdmvkit.disc", "PIL.ImageDraw", "PIL.ImageFont",
           "boxset.core", "boxset.draw", "boxset.html", "boxset.iso", "boxset.gui.app"]

a = Analysis([os.path.join(ROOT, "packaging", "launch_gui.py")], pathex=[ROOT], datas=datas,
             binaries=binaries, hiddenimports=hidden, excludes=["tkinter", "matplotlib", "numpy"])
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "packaging", "boxset.ico")

app = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Boxset", console=False, icon=icon)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="boxset-cli", console=True, icon=icon)
coll = COLLECT(app, cli, a.binaries, a.datas, name="Boxset")
