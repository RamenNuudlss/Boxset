# Boxset

Put a movie collection on one Blu-ray with its own themed menu. Add your movies,
pick a theme, press **Build disc**. Boxset reads every film's chapters, fits the
whole set to the disc, renders every menu screen, encodes the films and writes a
disc that plays in a standard Blu-ray player.

## Using it

1. **Films.** Drop video files or a folder into the window. Titles and years are
   read from the file names; fix anything inline. Drag to set the disc order. The
   disc on the right shows how much each film takes and the picture quality the
   chosen disc size allows.
2. **Menu.** Pick a theme and adjust its settings. *Render menus* builds every
   screen from your films and chapters, and you can click through them with the
   arrow keys and Enter exactly as the remote will.
3. **Build.** Press *Build disc*. Everything else is automatic: menus, encoding
   (the long part; stop any time and finished films are kept), the disc
   structure and, on Windows, a disc image. *Burn to disc* hands the image to
   Windows' own disc burner.

Projects save themselves to `Documents\Boxset\<collection name>`.

### Themes

Themes are packs (`.boxtheme`). Double-click one, or use *Install theme pack* in
the Menu view. Theme packs contain code, so only install packs from people you
trust. How to write one: [THEMES.md](THEMES.md).

### Good to know

- Try the first disc on a rewritable BD-RE in your actual player before burning
  write-once media.
- BD-100 discs need a player that supports BDXL.
- Each film keeps its first audio track as Dolby Digital (5.1 when the rip has it).

## Command line

`boxset-cli` (or `python -m boxset` from source) does the same work without the window:

```
boxset-cli check   project.boxset     read every rip, show the space plan
boxset-cli menus   project.boxset     render and check every menu screen
boxset-cli preview project.boxset     contact sheet of all screens
boxset-cli build   project.boxset     encode and write the disc (--iso, --fast, --skip-encode)
```

## Building from source

```
pip install -r requirements.txt
python -m boxset                 # the app (add --browser to open it in a browser tab)
```

FFmpeg must be on PATH when running from source.

### Releases

Push a tag like `v0.1.0` and the GitHub Actions workflow builds
`BoxsetSetup-0.1.0.exe` on Windows: PyInstaller app, FFmpeg bundled, Inno Setup
installer with file associations for `.boxset` and `.boxtheme`, and the WebView2
runtime installed on PCs that lack it. See `packaging/` and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the licences that ship with it.
