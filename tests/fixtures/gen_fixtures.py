"""Generates procedural placeholder art for the seed data: one portrait per
idol and one cover per album/single/EP/lightstick product. No AI image
generation was available in this environment, so these are deterministic
Pillow-drawn gradients/patterns/monograms color-themed off each idol's
idol_colors hex code — good enough to exercise the upload/storage pipeline
end to end, not meant to read as real character art.

Output: {idols,products}/<slug>.png, written next to this script — i.e. run
this from inside tests/fixtures/ (where it lives in the repo) and it
regenerates the fixtures in place.
"""
import hashlib
import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

OUT_ROOT = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = "/usr/share/fonts/truetype/google-fonts"
FALLBACK_FONT_DIR = "/usr/share/fonts/truetype/dejavu"

FONT_DISPLAY_BOLD = os.path.join(FONT_DIR, "Poppins-Bold.ttf")
FONT_TITLE_BOLD = "/mnt/skills/examples/canvas-design/canvas-fonts/BigShoulders-Bold.ttf"
FONT_LABEL = os.path.join(FONT_DIR, "Poppins-Bold.ttf")

if not os.path.exists(FONT_DISPLAY_BOLD):
    FONT_DISPLAY_BOLD = os.path.join(FALLBACK_FONT_DIR, "DejaVuSans-Bold.ttf")
if not os.path.exists(FONT_TITLE_BOLD):
    FONT_TITLE_BOLD = FONT_DISPLAY_BOLD
if not os.path.exists(FONT_LABEL):
    FONT_LABEL = FONT_DISPLAY_BOLD


def slugify(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def _seed_int(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16)


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    hex_code = hex_code.lstrip("#")
    return tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))


def relative_luminance(rgb) -> float:
    r, g, b = (c / 255.0 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_color(bg_rgb) -> tuple[int, int, int]:
    return (20, 18, 26) if relative_luminance(bg_rgb) > 0.55 else (250, 248, 252)


def shade(rgb, factor: float) -> tuple[int, int, int]:
    """factor > 1 lightens toward white, < 1 darkens toward black."""
    if factor >= 1:
        t = min(factor - 1, 1.0)
        return tuple(int(c + (255 - c) * t) for c in rgb)
    t = max(0.0, factor)
    return tuple(int(c * t) for c in rgb)


def gradient(size, color_a, color_b, mode="linear", angle=0):
    base = Image.linear_gradient("L") if mode == "linear" else Image.radial_gradient("L")
    base = base.resize((512, 512))
    if mode == "linear" and angle:
        base = base.rotate(angle, resample=Image.BICUBIC, expand=False)
        # rotating a gradient can pull in black corners past the frame edge;
        # crop back to the center where the gradient is still full-range.
        w, h = base.size
        cx, cy = w // 2, h // 2
        crop = min(w, h) // 3
        base = base.crop((cx - crop, cy - crop, cx + crop, cy + crop))
    base = base.resize(size)
    return ImageOps.colorize(base, black=color_a, white=color_b).convert("RGB")


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def draw_pattern(draw, size, kind, color, seed):
    w, h = size
    rng_offset = seed % 97
    if kind == "dots":
        step = 46
        r = 4
        for y in range(-step, h + step, step):
            for x in range(-step, w + step, step):
                ox = (rng_offset % 17) - 8
                draw.ellipse([x - r + ox, y - r, x + r + ox, y + r], fill=(*color, 60))
    elif kind == "diagonal":
        step = 34
        for i in range(-h, w + h, step):
            draw.line([(i, 0), (i + h, h)], fill=(*color, 55), width=6)
    elif kind == "grid":
        step = 40
        for x in range(0, w, step):
            draw.line([(x, 0), (x, h)], fill=(*color, 45), width=2)
        for y in range(0, h, step):
            draw.line([(0, y), (w, y)], fill=(*color, 45), width=2)
    elif kind == "rings":
        cx, cy = w // 2, h // 2
        for r in range(40, max(w, h), 60):
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(*color, 70), width=3)
    elif kind == "spikes":
        cx, cy = w // 2, int(h * 0.15)
        n = 10
        for i in range(n):
            ang = (2 * math.pi / n) * i + (seed % 100) / 100
            length = 260 + (i * 13) % 70
            x2 = cx + length * math.cos(ang)
            y2 = cy + length * math.sin(ang) * 0.6 + h * 0.3
            draw.line([(cx, cy + h * 0.3), (x2, y2)], fill=(*color, 40), width=3)


PATTERN_BY_HASH = ["dots", "diagonal", "grid", "rings"]


def monogram_portrait(name: str, act_label: str, hex_code: str, out_path: str):
    size = (512, 512)
    rgb = hex_to_rgb(hex_code)
    seed = _seed_int(name)
    angle = seed % 180
    dark = shade(rgb, 0.55)
    light = shade(rgb, 1.35)
    # alternate gradient direction so a full roster doesn't look identical
    if seed % 2 == 0:
        img = gradient(size, dark, light, mode="linear", angle=angle % 60)
    else:
        img = gradient(size, light, dark, mode="radial")

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    pattern = PATTERN_BY_HASH[seed % len(PATTERN_BY_HASH)]
    accent = contrast_color(rgb)
    draw_pattern(odraw, size, pattern, accent, seed)
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(img)
    parts = [p for p in name.split(" ") if p]
    initials = "".join(p[0] for p in parts[:2]).upper()
    text_color = contrast_color(rgb)
    font = load_font(FONT_DISPLAY_BOLD, 220)
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (size[0] - tw) / 2 - bbox[0], (size[1] - th) / 2 - bbox[1] - 20
    shadow_color = shade(text_color, 0.3 if relative_luminance(rgb) > 0.55 else 1.6)
    draw.text((tx + 4, ty + 4), initials, font=font, fill=(*shadow_color, 120))
    draw.text((tx, ty), initials, font=font, fill=text_color)

    label_font = load_font(FONT_LABEL, 30)
    label = act_label.upper()
    lb = draw.textbbox((0, 0), label, font=label_font)
    lw = lb[2] - lb[0]
    draw.rectangle([0, size[1] - 64, size[0], size[1]], fill=(*shade(rgb, 0.35), 210))
    draw.text(((size[0] - lw) / 2 - lb[0], size[1] - 50), label, font=label_font, fill=(250, 248, 252))

    img.convert("RGB").save(out_path, "PNG")


GENRE_MOTIF = {
    "pop": "rings",
    "citypop": "diagonal",
    "anime": "spikes",
    "gothic": "grid",
    "vocaloid": "grid",
    "rnb": "rings",
}


def cover_art(title: str, act_label: str, hex_code: str, motif_key: str, out_path: str, size=(600, 600)):
    rgb = hex_to_rgb(hex_code)
    seed = _seed_int(title, "cover")
    dark = shade(rgb, 0.4)
    light = shade(rgb, 1.25)
    img = gradient(size, dark, light, mode="linear", angle=(seed % 90))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    pattern = GENRE_MOTIF.get(motif_key, "dots")
    draw_pattern(odraw, size, pattern, contrast_color(rgb), seed)
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    # darken a band for legible title text
    band = Image.new("RGBA", size, (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(band)
    bdraw.rectangle([0, size[1] - 190, size[0], size[1]], fill=(*shade(rgb, 0.25), 190))
    img = Image.alpha_composite(img, band)

    draw = ImageDraw.Draw(img)
    title_font = load_font(FONT_TITLE_BOLD, 46)
    words = title.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), trial, font=title_font)
        if bbox[2] - bbox[0] > size[0] - 60 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    lines = lines[:3]

    y = size[1] - 175
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        lw = bbox[2] - bbox[0]
        draw.text(((size[0] - lw) / 2 - bbox[0], y), line, font=title_font, fill=(250, 248, 252))
        y += 52

    act_font = load_font(FONT_LABEL, 26)
    ab = draw.textbbox((0, 0), act_label.upper(), font=act_font)
    aw = ab[2] - ab[0]
    draw.text(((size[0] - aw) / 2 - ab[0], y + 4), act_label.upper(), font=act_font, fill=shade(contrast_color(rgb), 1.0))

    img.convert("RGB").save(out_path, "PNG")


def lightstick_art(act_label: str, hex_code: str, out_path: str, size=(320, 720)):
    rgb = hex_to_rgb(hex_code)
    bg = (16, 15, 22)
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = size
    cx = w // 2

    # glow behind the bulb
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    bulb_cy = int(h * 0.24)
    for r, alpha in [(150, 25), (110, 45), (75, 70)]:
        gdraw.ellipse([cx - r, bulb_cy - r, cx + r, bulb_cy + r], fill=(*rgb, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    draw = ImageDraw.Draw(img, "RGBA")

    # bulb (translucent capsule)
    bulb_w, bulb_h = 150, 190
    bx0, by0 = cx - bulb_w // 2, bulb_cy - bulb_h // 2
    bx1, by1 = cx + bulb_w // 2, bulb_cy + bulb_h // 2
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=70, fill=(*rgb, 235), outline=(255, 255, 255, 160), width=3)
    # inner highlight
    draw.ellipse([cx - 34, by0 + 26, cx + 6, by0 + 100], fill=(255, 255, 255, 110))

    # neck
    neck_top = by1 - 6
    neck_bot = neck_top + 40
    draw.rectangle([cx - 22, neck_top, cx + 22, neck_bot], fill=(70, 68, 78, 255))

    # handle
    handle_top = neck_bot
    handle_bot = int(h * 0.94)
    draw.rounded_rectangle([cx - 46, handle_top, cx + 46, handle_bot], radius=26,
                            fill=(232, 230, 236, 255), outline=(*shade(rgb, 0.6), 255), width=6)
    # handle grip lines
    for gy in range(handle_top + 40, handle_bot - 20, 28):
        draw.line([(cx - 30, gy), (cx + 30, gy)], fill=(*shade(rgb, 0.7), 140), width=4)

    # small emblem dot near the base
    draw.ellipse([cx - 14, handle_bot - 70, cx + 14, handle_bot - 42], fill=(*rgb, 255))

    draw = ImageDraw.Draw(img)
    label_font = load_font(FONT_LABEL, 24)
    label = act_label.upper()
    lb = draw.textbbox((0, 0), label, font=label_font)
    lw = lb[2] - lb[0]
    draw.text(((w - lw) / 2 - lb[0], h - 34), label, font=label_font, fill=(235, 233, 240))

    img.convert("RGB").save(out_path, "PNG")


# ---------------------------------------------------------------------------
# Roster / catalog (must match seed.py's IDOLS / RELEASES / LIGHTSTICKS)
# ---------------------------------------------------------------------------

IDOLS = [
    # (name, act_label, hex_code)
    ("Hinata Kisaragi", "Sakura Prism", "#FFB3D9"),
    ("Momoka Serizawa", "Sakura Prism", "#FFD3B0"),
    ("Yui Amamiya", "Sakura Prism", "#FFF3B0"),
    ("Riko Fujimori", "Sakura Prism", "#FFB570"),
    ("Nozomi Aizawa", "Sakura Prism", "#FFC4DD"),
    ("Sora Minase", "Nagisa Melody", "#A0E7E5"),
    ("Ao Tachibana", "Nagisa Melody", "#AEE1FF"),
    ("Nagi Hoshikawa", "Nagisa Melody", "#B5EAD7"),
    ("Kanade Umino", "Nagisa Melody", "#D9B8FF"),
    ("Akira Hoshimiya", "Kessho Stars", "#C7CEEA"),
    ("Ren Kazahaya", "Kessho Stars", "#FFD966"),
    ("Towa Kirishima", "Kessho Stars", "#FFB84D"),
    ("Hikaru Otonashi", "Kessho Stars", "#4DE8E0"),
    ("Yuzuki Amagi", "Kessho Stars", "#E4C1F9"),
    ("Aoi Kurenai", "Yozora Requiem", "#2B2730"),
    ("Suzune Yamikawa", "Yozora Requiem", "#8B1E3F"),
    ("Karen Shirayuki", "Yozora Requiem", "#6B2E5F"),
    ("Mizuki Tsukishiro", "Yozora Requiem", "#2E2A5E"),
    ("Mira Kanade", "Program:HEART", "#2ED9C3"),
    ("Rio Kirisame", "Program:HEART", "#D8D8E0"),
    ("Nana Shirakawa", "Program:HEART", "#B9A6D9"),
    ("Kohaku Amemiya", "Program:HEART", "#B3E5E0"),
    ("Rin Amane", "Solo", "#F5F0E6"),
    ("Kaede Shirogane", "Solo", "#C4283C"),
    ("Yoru Kuon", "Solo", "#B8577E"),
]

RELEASES = [
    # (slug_title, cover_title, act_label, hex_code, motif_key)
    ("sakura-prism-hanabi-ranman", "Hanabi Ranman", "Sakura Prism", "#FFB3D9", "pop"),
    ("sakura-prism-sparkle-signal", "Sparkle Signal", "Sakura Prism", "#FFC4DD", "pop"),
    ("nagisa-melody-midnight-drive", "Midnight Drive", "Nagisa Melody", "#A0E7E5", "citypop"),
    ("kessho-stars-starlight-oath", "Starlight Oath", "Kessho Stars", "#C7CEEA", "anime"),
    ("yozora-requiem-requiem-for-dawn", "Requiem for Dawn", "Yozora Requiem", "#2B2730", "gothic"),
    ("program-heart-recompile", "Recompile", "Program:HEART", "#2ED9C3", "vocaloid"),
    ("program-heart-debug-heart", "Debug Heart", "Program:HEART", "#39C5BB", "vocaloid"),
    ("rin-amane-tideline", "Tideline", "Rin Amane (Solo)", "#F5F0E6", "rnb"),
    ("kaede-shirogane-crimson-overture", "Crimson Overture", "Kaede Shirogane (Solo)", "#C4283C", "anime"),
    ("yoru-kuon-ghost-in-the-chorus", "Ghost in the Chorus", "Yoru Kuon (Solo)", "#B8577E", "vocaloid"),
]

LIGHTSTICKS = [
    # (slug, act_label, hex_code)
    ("sakura-prism-lightstick", "Sakura Prism", "#FFB3D9"),
    ("nagisa-melody-lightstick", "Nagisa Melody", "#A0E7E5"),
    ("kessho-stars-lightstick", "Kessho Stars", "#C7CEEA"),
    ("yozora-requiem-lightstick", "Yozora Requiem", "#8B1E3F"),
    ("program-heart-lightstick", "Program:HEART", "#2ED9C3"),
    ("rin-amane-penlight", "Rin Amane", "#F5F0E6"),
    ("kaede-shirogane-penlight", "Kaede Shirogane", "#C4283C"),
    ("yoru-kuon-penlight", "Yoru Kuon", "#B8577E"),
]


def main():
    idols_dir = os.path.join(OUT_ROOT, "idols")
    products_dir = os.path.join(OUT_ROOT, "products")
    os.makedirs(idols_dir, exist_ok=True)
    os.makedirs(products_dir, exist_ok=True)

    for name, act_label, hexc in IDOLS:
        path = os.path.join(idols_dir, f"{slugify(name)}.png")
        monogram_portrait(name, act_label, hexc, path)
    print(f"idol portraits: {len(IDOLS)}")

    for slug, title, act_label, hexc, motif in RELEASES:
        path = os.path.join(products_dir, f"{slug}.png")
        cover_art(title, act_label, hexc, motif, path)
    print(f"release covers: {len(RELEASES)}")

    for slug, act_label, hexc in LIGHTSTICKS:
        path = os.path.join(products_dir, f"{slug}.png")
        lightstick_art(act_label, hexc, path)
    print(f"lightstick images: {len(LIGHTSTICKS)}")

    total = len(IDOLS) + len(RELEASES) + len(LIGHTSTICKS)
    print(f"TOTAL: {total}")


if __name__ == "__main__":
    main()
