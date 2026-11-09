# Writing a Boxset theme

A theme decides everything on the disc that isn't the films themselves: how many
menu screens there are, what each one looks like, how its buttons look when
they're highlighted and pressed, and where every button leads. Boxset hands the
theme the films, chapters and chapter frames, then checks what the theme makes
against Blu-ray rules and builds the disc from it.

Themes are Python. Screens can be drawn as ordinary web pages (HTML and CSS,
rendered with Microsoft Edge) or as images made any other way, and a theme can
mix both.

- [A complete theme in 40 lines](#a-complete-theme-in-40-lines)
- [Where themes live](#where-themes-live)
- [The Theme class](#the-theme-class)
- [Settings the app shows](#settings-the-app-shows)
- [What ctx gives you](#what-ctx-gives-you)
- [Screens drawn with HTML](#screens-drawn-with-html)
- [Screens drawn as images](#screens-drawn-as-images)
- [Actions, navigation and playlists](#actions-navigation-and-playlists)
- [Blu-ray rules](#blu-ray-rules)
- [Testing a theme](#testing-a-theme)
- [Sharing a theme](#sharing-a-theme)
- [Tips](#tips)

## A complete theme in 40 lines

A main menu with the collection's title and one button per film. Save it as
`themes/simple-list/theme.py` next to a project file, and it appears in the
app's theme list.

```python
from boxset.core import BaseTheme, act

CSS = """
body { margin: 0; width: 1920px; height: 1080px; background: #101820; color: #fff;
       font: 600 44px/1.2 system-ui, sans-serif; }
h1 { position: absolute; left: 120px; top: 80px; margin: 0; font-size: 96px; }
.btn { position: absolute; left: 120px; width: 960px; height: 76px; padding: 0 28px;
       display: flex; align-items: center; border-radius: 10px; }
.btn[data-state="selected"]  { background: ACCENT; color: #101820; }
.btn[data-state="activated"] { background: #fff; color: #101820; }
"""


class Theme(BaseTheme):
    name = "Simple list"
    description = "A title and one button per film."
    author = "You"
    version = "1.0"
    limits = {"min_films": 1, "max_films": 9}
    options = [
        {"key": "title", "label": "Title", "type": "text", "default": "MY COLLECTION"},
        {"key": "accent", "label": "Highlight colour", "type": "color", "default": "#F2B134",
         "choices": ["#F2B134", "#4FC3F7", "#EF5350"]},
    ]

    def build(self, ctx):
        css = CSS.replace("ACCENT", self.options["accent"])
        rows = "".join(
            f'<div class="btn" data-button="f{f.number}" data-action="{act.title(f.number)}" '
            f'style="top:{260 + i * 88}px">{ctx.esc(f.title)}</div>'
            for i, f in enumerate(ctx.films))
        html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head>"
                f"<body><h1>{ctx.esc(self.options['title'])}</h1>{rows}</body></html>")
        ctx.html.menu("main", html)
        ctx.start("main")
```

That's a working disc: the first button starts highlighted, up and down move
between films, and OK plays the highlighted one. The built-in themes in
[`boxset/themes/`](boxset/themes) are complete, larger examples: Tachometer
draws with Pillow, and Marquee draws with HTML, including a motion background.

## Where themes live

Boxset looks for theme folders, each containing a `theme.py`, in this order:

1. `themes\` next to the open project file. Use this while you're making one.
2. `%APPDATA%\Boxset\themes\`, where installed theme packs go.
3. The built-in themes inside the app.

The folder's name is the theme's id, which is what a project stores as its
`theme`. A theme folder can hold anything else it needs: fonts, images, music,
CSS.

## The Theme class

```python
class Theme(BaseTheme):
    name = "Marquee"                 # shown in the app
    description = "One line."        # shown under the name
    author = "Your name"
    version = "1.0"
    limits = {"min_films": 1, "max_films": 11}   # the app warns outside this range
    options = [...]                  # settings, see below
    film_fields = [...]              # extra per-film fields, see below

    def build(self, ctx):            # make every menu, then:
        ctx.start("main")            # the menu shown when the disc goes in
```

`self.options` holds the project's settings for this theme, with the `default`
of every option you declared filled in. Raise `RuntimeError("…")` from `build`
to stop with a message the user will see, for example when there are more films
than your layout fits.

Add a `preview.jpg` (1280 × 720) to the folder. The app shows it on the theme's
card.

## Settings the app shows

Each entry in `options` becomes a control in the app's Menu tab:

| `type` | Control | Value in `self.options` | Extra keys |
|---|---|---|---|
| `text` | Text box | string | |
| `bool` | Switch | `True` / `False` | |
| `color` | Swatches plus a colour picker | `"#RRGGBB"` | `choices`: list of preset colours |
| `choice` | Drop-down | one of `choices` | `choices`: list of strings |
| `file` | File picker | a path, or `None` | `filter`: `"audio"` for music |
| `order` | Switch plus a reorderable film list | list of film numbers, or `None` | |

Every type also takes `key`, `label`, `default` and an optional `help` line.
Read a file setting with `ctx.user_file(self.options["key"])`. Read an order
setting with `ctx.story_order(self.options["key"])`, which returns `None` when
it's switched off, matches release order, or is out of date because films were
added or removed.

`film_fields` adds text fields to each film's details in the Films tab:

```python
film_fields = [{"key": "tagline", "label": "Tagline", "type": "text"}]
```

Their values arrive as `film.extra["tagline"]`.

## What ctx gives you

| Name | What it is |
|---|---|
| `ctx.films` | The films in disc order |
| `film.number`, `.title`, `.year`, `.place`, `.spinoff` | From the Films tab (`year` may be `None`) |
| `film.extra` | Any other field set on the film, including your `film_fields` |
| `film.duration`, `.minutes`, `.runtime` | Length in seconds, in minutes, and as `"2 HR 11 MIN"` |
| `film.chapters` | Each has `.number`, `.start` (seconds), `.timecode` (`"0:12:34"`) and `.thumb` (a frame grab's path, or `None`) |
| `ctx.total_seconds` | The whole collection's running time |
| `ctx.film(n)` | Film number `n` |
| `ctx.pages(items, n)` | Split a list (such as chapters) into pages of `n` |
| `ctx.story_order(value)` | Validate an `order` setting (see above) |
| `ctx.asset("img/x.png")` | Path to a file in your theme folder |
| `ctx.user_file(path)` | Path to a file the user chose in your settings |
| `ctx.uri(path)` | A `file://` URL for using any local file inside HTML |
| `ctx.esc(text)` | Escape text for HTML |
| `ctx.log(text)` | A progress line shown while menus render |
| `ctx.html` | The HTML renderer (next section) |

## Screens drawn with HTML

```python
ctx.html.menu(menu_id, html, music=None, animate=None)
```

Each screen is a complete HTML page that the renderer shows at exactly
1920 × 1080. Relative URLs (`url(fonts/X.ttf)`, `<img src="img/bg.jpg">`) load from
your theme folder; for anything else, such as chapter frames, use `ctx.uri()`.

Mark each button with attributes:

| Attribute | Meaning |
|---|---|
| `data-button="id"` | Makes the element a button. Ids must be unique on the screen |
| `data-action="…"` | What it does (see [actions](#actions-navigation-and-playlists)) |
| `data-default` | Highlighted when the menu opens (otherwise the first button) |
| `data-nav-up`, `-down`, `-left`, `-right` | Button id the arrow key goes to. Leave out for "nearest in that direction" |
| `data-pad="24"` | Extra pixels captured around the element, for glows and shadows |
| `data-auto` | Runs the action as soon as the button is selected, without OK. Use it to flip between pages (the Encore theme's Cover Flow moves this way). Can't be the default button |

Style the three states on the button element:

```css
.ticket[data-state="normal"]    { … }
.ticket[data-state="selected"]  { … }   /* highlighted */
.ticket[data-state="activated"] { … }   /* the moment OK is pressed */
```

How a screen is captured:

1. The page is shot with the buttons hidden. That's the background, in full colour.
2. For each state, the page is shot with everything except the buttons hidden,
   and each button is cut out of that shot. Anything inside a button element
   belongs to the button; anything outside it belongs to the background.

**Motion backgrounds.** `animate=6.0` records six seconds of the page's CSS
animations (with the buttons hidden) as the background video, which loops on the
disc. Make the animation loop seamlessly over that length. For canvas or other
script-driven animation, define `window.boxsetFrame = (ms) => { … }`; the recorder
calls it with the time of each frame.

**Music.** `music=path` loops an audio file (MP3, WAV, FLAC, M4A) while the menu is
showing.

**Snippets.** `ctx.html.image(html, width, height)` renders any HTML to a Pillow
image, which is useful for text effects inside an image-drawn theme.

## Screens drawn as images

```python
m = ctx.menu("main", background, music=None)
m.button("play", x, y, {"normal": img, "selected": img2, "activated": img3}, act.title(1))
m.chain(["play", "scenes", "next"])    # up/down order, wrapping around
m.default = "play"
```

- `background`: a Pillow image, or the path of an image or video file.
- Button images are Pillow images (RGBA) or paths, all placed at `(x, y)`. The
  states may differ in size; transparent edges are trimmed automatically.
  `activated` falls back to `selected` when left out.
- `m.chain(ids, axis="horizontal")` links left and right instead.
- `m.get(id).nav["right"] = "back"` sets a single direction by hand.
- `m.button(..., auto=True)` makes a button act the moment it's selected.

`boxset/draw.py` has the helpers the Tachometer theme uses: anti-aliased shapes,
letter-spaced text, slanted boxes and the dial.

## Actions, navigation and playlists

| Action | Does |
|---|---|
| `act.title(n)` | Plays film `n` from the start |
| `act.chapter(n, c)` | Plays film `n` from chapter `c` |
| `act.menu(id)` | Opens a menu on its default button |
| `act.menu(id, button)` | Opens a menu with `button` highlighted |
| `act.playall()` | Plays every film in disc order |
| `act.playlist(pid)` | Plays a playlist made with `ctx.playlist(pid, [3, 1, 2])` |
| `act.back()` | Returns to the previous menu |

After playback, the player goes back to the start menu unless you say otherwise:

```python
ctx.after_film(n, act.menu(f"film{n:02d}", "play"))   # back to the film's own page
ctx.after_playlist("story", act.menu("main", "story"))
```

## Blu-ray rules

Players enforce these, so Boxset checks every theme against them and refuses to
build until they pass:

- Buttons can't overlap. This includes glows and shadows, so leave gaps wider
  than your glow.
- Every button must be fully on the 1920 × 1080 screen.
- A menu can have at most 255 buttons.
- Every action must point at something that exists: a film, chapter, menu, button
  or playlist.

The error names the menu and buttons involved, for example:

```
menu 'main': buttons 'play' and 'pick' overlap
menu 'film03', button 'next': opens menu 'film04', which doesn't exist
```

Also: button graphics are reduced to **256 colours per menu**, shared by every
button on it. Boxset does this automatically. Put photos, gradients and soft glows
in the background, which keeps full colour, and keep button art crisp and flat.

## Testing a theme

- **In the app:** open a project, pick your theme on the Menu tab, press **Render
  menus**, and drive it with the arrow keys, Enter and Backspace. The app reloads
  `theme.py` each time you render.
- **From the command line:**

  ```
  boxset-cli menus "My collection.boxset" --theme simple-list --force
  boxset-cli preview "My collection.boxset"      # build\menus_preview.jpg
  ```

- **On a player:** make a **Quick test build** and burn it to a BD-RE.

## Sharing a theme

Zip the theme folder and rename the zip to `<name>.boxtheme`. Double-clicking
it installs it. Include `preview.jpg`, any fonts you use (and their licences), and
nothing you don't have the right to share.

Theme packs run code on the user's PC, so say clearly where yours comes from.

## Tips

- Design for a TV at a distance: big text, strong contrast, and the
  highlighted button obvious at a glance.
- Keep important things inside the safe area, about 96 px from the sides and
  54 px from the top and bottom, because some TVs crop the edges.
- Test with the most and fewest films your `limits` allow, with long titles, and
  with films that have one chapter (no scene selection) or many.
- The fonts the built-in themes use are in `boxset/fonts/` and
  `boxset/themes/marquee/fonts/`, under the SIL Open Font License.
