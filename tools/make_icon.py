"""Render the integration icon (brand/icon.png and icon@2x.png) with Pillow.

Same look as docs/images/device.svg: grey battery with heat sink fins and
the black display showing a battery and Wi-Fi symbol.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "powerness" / "brand"
SCALE = 8  # draw large, then downsample for smooth edges


def render(size: int) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return [x0 * s, y0 * s, x1 * s, y1 * s]

    # Heat sink with fins
    d.rounded_rectangle(box(0.06, 0.20, 0.94, 0.34), radius=0.03 * s, fill=(206, 210, 213))
    for i in range(14):
        x = 0.10 + i * 0.0615
        d.rectangle(box(x, 0.22, x + 0.012, 0.33), fill=(158, 163, 168))
    # Body
    d.rounded_rectangle(box(0.07, 0.30, 0.93, 0.78), radius=0.06 * s, fill=(196, 199, 202))
    # Base
    d.rounded_rectangle(box(0.08, 0.74, 0.92, 0.81), radius=0.035 * s, fill=(130, 134, 138))
    # Display
    d.rounded_rectangle(box(0.30, 0.43, 0.70, 0.63), radius=0.03 * s, fill=(8, 8, 8))
    # Battery symbol with bars
    d.rounded_rectangle(
        box(0.36, 0.48, 0.55, 0.57), radius=0.01 * s, outline=(240, 240, 240), width=int(0.012 * s)
    )
    d.rectangle(box(0.55, 0.505, 0.565, 0.545), fill=(240, 240, 240))
    for i in range(4):
        x = 0.375 + i * 0.043
        d.rectangle(box(x, 0.495, x + 0.033, 0.555), fill=(46, 164, 78))
    # Wi-Fi symbol
    for r, w in ((0.055, 0.011), (0.033, 0.011)):
        d.arc(
            box(0.63 - r, 0.56 - r, 0.63 + r, 0.56 + r),
            220,
            320,
            fill=(240, 240, 240),
            width=int(w * s),
        )
    d.ellipse(box(0.622, 0.548, 0.638, 0.564), fill=(240, 240, 240))

    return img.resize((size, size), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    render(256).save(OUT / "icon.png", optimize=True)
    render(512).save(OUT / "icon@2x.png", optimize=True)
    print(f"written to {OUT}")
