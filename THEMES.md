# Writing a Boxset theme

A theme is a folder with a `theme.py`. Zip the folder and rename it to
`<name>.boxtheme` to share it: double-clicking the file installs it into Boxset.
While you work on one, put the folder in `themes/` next to your project file and
it appears in the app's theme list straight away.
The theme decides every screen, every button and how the menus link together.
Boxset supplies the data and checks the result against what Blu-ray players can do.

```python
from boxset.core import BaseTheme, act

class Theme(BaseTheme):
    name = "My theme"
    description = "One line shown by `boxset themes`."

    def build(self, ctx):
        ...
        ctx.start("main")   # menu shown when the disc goes in
```

## What `ctx` gives you

| | |
|---|---|
| `ctx.films` | list of films, in disc order |
| `film.number`, `.title`, `.year`, `.place`, `.spinoff` | from the film list |
| `film.extra` | every other field set for this film (declare them in `film_fields` so the app shows them) |
| `film.duration`, `.runtime`, `.minutes` | from the rip |
| `film.chapters` | each has `.number`, `.start` (s), `.timecode`, `.thumb` (frame grab path) |
| `self.options` | the theme's settings, with your `options` defaults filled in |
| `ctx.total_seconds` | combined running time |
| `ctx.asset("img/x.png")` | a file inside the theme folder |
| `ctx.user_file(path)` | a file chosen in the theme's settings |
| `ctx.pages(items, n)` | split a list into pages of n |
| `ctx.uri(path)`, `ctx.esc(text)` | for HTML screens |

## Making screens

**Two ways, mix freely.**

1. **HTML/CSS** (anything a web page can look like):

   ```python
   ctx.html.menu("main", html, music=ctx.asset("loop.mp3"), animate=8.0)
   ```

   Mark buttons with `data-button="id"` and `data-action="…"`; style the
   states with `[data-state="normal|selected|activated"]`. Relative URLs resolve
   against the theme folder. `animate=seconds` records CSS animations
   (or `window.boxsetFrame = ms => …` for canvas/JS) into a looping video
   background. Full attribute list at the top of `boxset/html.py`.

2. **Images** (Pillow, pre-made art, anything that yields an image):

   ```python
   m = ctx.menu("main", background=img_or_path_or_video, music=None)
   m.button("play", x, y, {"normal": a, "selected": b, "activated": c}, act.title(1))
   m.chain(["play", "scenes", "next"])          # d-pad order
   ```

## Actions

`act.title(n)` · `act.chapter(n, c)` · `act.menu(id)` · `act.menu(id, button)` ·
`act.playall()` · `act.playlist(id)` (define with `ctx.playlist(id, [film numbers])`) ·
`act.back()`

## Rules Boxset enforces (Blu-ray, not Boxset)

- Buttons can't overlap (glows count; keep gaps wider than your glow).
- Buttons must sit fully on the 1920×1080 screen.
- At most 255 buttons per menu.
- Button art is reduced to 256 colours per menu automatically. Backgrounds keep full colour,
  so put gradients and photos in the background, and keep buttons crisp.
- Every action must point at something that exists.

`boxset menus` lists anything that breaks these before a disc is ever built.
