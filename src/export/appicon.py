"""The app's mark, drawn rather than shipped.

A PWA wants icons at several sizes, and an icon file per size is three or four
more things to upload. These are drawn at build time and handed back as data
URIs, so they travel inside the manifest and inside the page — which is what
keeps the whole app to three files.

Geometric on purpose. The obvious mark is the brand's own type, and type means
a font file PIL can load: the faces this project ships are woff2, which it
cannot, and reaching for a system font makes the build depend on which machine
ran it. Six pips in a die's six-face needs no font, means the name, and is
still legible at 48 pixels.
"""
from __future__ import annotations

import base64
import io

#: The mark's two colors. Deliberately the ink and the paper of the page it
#: opens, so the icon and the first frame of the app are the same object.
INK = (22, 24, 29)
PAPER = (245, 243, 238)

#: A maskable icon is cropped to whatever shape the platform likes — a circle
#: on some Androids, a squircle on others — so everything that must survive
#: sits inside the middle 80%. The spec calls for at least this much.
MASKABLE_SAFE = 0.8


def _pips(draw, box, color) -> None:
    """A die's six face: two columns of three."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    r = min(w / 2 / 2.6, h / 3 / 2.6)
    for col in range(2):
        for row in range(3):
            cx = x0 + w * (0.27 + 0.46 * col)
            cy = y0 + h * (0.18 + 0.32 * row)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def png(size: int, *, maskable: bool = False) -> bytes:
    """One icon, as PNG bytes."""
    from PIL import Image, ImageDraw

    # Drawn at 4x and reduced, because PIL has no antialiasing on shapes —
    # a circle drawn straight at 48px has visible stair-stepping on its edge.
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if maskable:
        # Full bleed: the platform crops it, so a transparent margin would
        # just become a smaller icon inside whatever shape it chooses.
        d.rectangle([0, 0, s, s], fill=INK)
        pad = s * (1 - MASKABLE_SAFE) / 2 + s * 0.10
    else:
        radius = s * 0.22
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=INK)
        pad = s * 0.22

    _pips(d, (pad, pad, s - pad, s - pad), PAPER)
    img = img.resize((size, size), Image.LANCZOS)
    # Two colors and the antialiased edge between them. A truecolour PNG of
    # that is 28KB at 512px and a 16-entry palette of it is 5.6KB, which
    # matters because these travel as base64 inside the manifest — where every
    # byte is a third larger again. FASTOCTREE because it is the only method
    # PIL will quantize an image with an alpha channel by.
    img = img.quantize(colors=16, method=Image.FASTOCTREE)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def data_uri(size: int, *, maskable: bool = False) -> str:
    return ("data:image/png;base64,"
            + base64.b64encode(png(size, maskable=maskable)).decode("ascii"))
