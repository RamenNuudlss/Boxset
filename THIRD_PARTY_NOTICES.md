# Third-party software in Boxset

Boxset bundles or uses the following. Each keeps its own licence.

| Component | Use | Licence | Source |
|---|---|---|---|
| FFmpeg (gyan.dev "essentials" build, with libx264) | Encoding films and menus, reading files | GPL-3.0 (this build) | https://ffmpeg.org, build: https://www.gyan.dev/ffmpeg/builds/ |
| bdmvkit 0.7 | Writing the Blu-ray disc structure | LGPL-3.0-or-later | https://github.com/kajisho5/bdmvkit |
| Pillow | Drawing menu graphics | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow |
| Playwright for Python | Rendering HTML themes with Microsoft Edge | Apache-2.0 | https://github.com/microsoft/playwright-python |
| pywebview | The app window | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| Python | Runtime | PSF License | https://www.python.org |
| Archivo, Barlow, Barlow Condensed, Bebas Neue, Courier Prime, Limelight | Interface and theme fonts | SIL Open Font License 1.1 | https://fonts.google.com |

FFmpeg runs as a separate program (`bin/ffmpeg.exe`). Its GPL licence requires that
anyone distributing it also offers the matching source code: link to the exact
release the build used (gyan.dev publishes the version and source for each build),
or ship that source alongside the installer.
