#!/usr/bin/env python3
"""
image_creator.py — IMDb-themed movie poster overlay or cover card.
Called by n8n Execute Command node.

Usage:
    python3 overlay.py \
        --input   "https://media.themoviedb.org/t/p/w440_and_h660_face/tlPgDzwIE7VYYIIAGCTUOnN4wI1.jpg" \
        --rating  "8.3" \
        --title   "Oppenheimer" \
        --genres  "History,Drama,Thriller" \
        --year    "2023" \
        --movie-id "872585" \
        --output  "/tmp/n8n-movies/872585_overlay.jpg" \
        --s3-bucket "YOUR_BUCKET_NAME" \
        --s3-region "ap-south-1"

Cover mode (no rating/genres/year; two teaser lines + swipe CTA; no title; same S3 key):

    python3 image_creator.py --image-type cover \\
        --input "..." --title "The Matrix" --movie-id "603" \\
        --output "/tmp/n8n-movies/603_overlay.jpg" \\
        --s3-bucket "YOUR_BUCKET_NAME" --s3-region "ap-south-1"

Fonts: place TTF files in fonts/ next to this script (see fonts/README.txt), or set
RECOMMENDLI_FONTS_DIR. Optional: RECOMMENDLI_ALLOW_SYSTEM_FONTS=0 to forbid OS fonts.
"""

import argparse
import os
import sys
import textwrap
from typing import List, Optional
import requests
import boto3
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()   # reads .env from the working directory into os.environ

# ── Bundled fonts (fonts/ next to this file, or RECOMMENDLI_FONTS_DIR) ─────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Used only if fonts/ has no .ttf/.otf (or none load).
BUNDLED_BOLD_NAMES = (
    "bold.ttf",
    "Inter-Bold.ttf",
    "Inter_18pt-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)
BUNDLED_REGULAR_NAMES = (
    "regular.ttf",
    "Inter-Regular.ttf",
    "Inter_18pt-Regular.ttf",
    "DejaVuSans.ttf",
)


def _is_color_emoji_font_filename(name: str) -> bool:
    """Exclude color-emoji fonts from body text (not used as UI type)."""
    n = name.lower().replace(" ", "")
    return (
        "notocoloremoji" in n
        or "coloremoji" in n
        or "applecoloremoji" in n
        or n == "emoji.ttf"
        or "seguiemj" in n
    )


def _scan_bundled_text_fonts(base: str) -> tuple[List[str], List[str]]:
    """
    All .ttf/.otf under `base` (recursive), split into bold vs regular candidates.
    If there is no bold file, regular files are used for both styles (single-weight families).
    Returns lists of absolute paths.
    """
    bold_paths: List[str] = []
    reg_paths: List[str] = []
    if not os.path.isdir(base):
        return bold_paths, reg_paths

    for root, _, files in os.walk(base):
        for f in files:
            if f.startswith(".") or not f.lower().endswith((".ttf", ".otf")):
                continue
            if _is_color_emoji_font_filename(f):
                continue
            full = os.path.join(root, f)
            if not os.path.isfile(full):
                continue
            n = f.lower()
            if any(
                k in n
                for k in (
                    "-bold",
                    "_bold",
                    "bold.ttf",
                    "bold.otf",
                    "semibold",
                    "demibold",
                    "extrabold",
                    "black",
                    "heavy",
                )
            ):
                bold_paths.append(full)
            else:
                reg_paths.append(full)

    bold_paths.sort()
    reg_paths.sort()
    if not bold_paths and reg_paths:
        bold_paths = list(reg_paths)
    if not reg_paths and bold_paths:
        reg_paths = list(bold_paths)
    return bold_paths, reg_paths


def fonts_base_dir() -> str:
    override = os.environ.get("RECOMMENDLI_FONTS_DIR", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(os.path.expandvars(override)))
    return os.path.join(_SCRIPT_DIR, "fonts")


def _allow_system_font_fallback() -> bool:
    return os.environ.get("RECOMMENDLI_ALLOW_SYSTEM_FONTS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


# ── IMDB brand colours ─────────────────────────────────────────────────────────
IMDB_YELLOW   = (245, 197, 24)       # #F5C518
IMDB_BLACK    = (0,   0,   0)
WHITE         = (255, 255, 255)
GREY_LIGHT    = (180, 180, 180)

COVER_BODY_LINE1 = "Loved this one? We've got a hunch"
COVER_BODY_LINE2 = "you'll love what's next..."
COVER_BODY_CTA_TEXT = "Swipe right to find your next movie night obsession! "
COVER_BODY_CTA_EMOJI = "\U0001f37f\u2728"
COVER_BODY_LINE3 = COVER_BODY_CTA_TEXT + COVER_BODY_CTA_EMOJI

# Cover mode: three text lines, no movie title; lighter gradient/scrim than IMDb overlay.
COVER_TEXT_PRIMARY = (250, 250, 250)
COVER_TEXT_SECONDARY = (175, 182, 192)  # CTA line
COVER_TEXT_SHADOW = (14, 16, 20)        # subtle outline for contrast on posters

# Cover-only: less of the poster darkened (gradient band + scrim start).
COVER_GRADIENT_FRACTION = 0.48
COVER_SCRIM_START_FRAC = 0.58          # scrim from this y down (larger = smaller dark region)
COVER_SCRIM_ALPHA_MAX = 165

# ── System font fallback (optional; disable with RECOMMENDLI_ALLOW_SYSTEM_FONTS=0) ─
FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",   # macOS (explicit bold)
        "/System/Library/Fonts/Supplemental/Verdana Bold.ttf", # macOS fallback
        "C:/Windows/Fonts/arialbd.ttf",                        # Windows
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",        # macOS
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ],
}

BUNDLED_EMOJI_NAMES = (
    "emoji.ttf",
    "NotoColorEmoji.ttf",
)

EMOJI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf",
    "/usr/local/share/fonts/NotoColorEmoji.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
]


def resolve_emoji_font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    base = fonts_base_dir()
    for name in BUNDLED_EMOJI_NAMES:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    if os.path.isdir(base):
        for root, _, files in os.walk(base):
            for f in files:
                if not f.lower().endswith((".ttf", ".otf")) or f.startswith("."):
                    continue
                if not _is_color_emoji_font_filename(f):
                    continue
                path = os.path.join(root, f)
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    if not _allow_system_font_fallback():
        return None
    for path in EMOJI_FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            if path.lower().endswith(".ttc"):
                for idx in range(4):
                    try:
                        return ImageFont.truetype(path, size, index=idx)
                    except OSError:
                        continue
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return None


def resolve_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    base = fonts_base_dir()
    bold_paths, reg_paths = _scan_bundled_text_fonts(base)
    for path in (bold_paths if style == "bold" else reg_paths):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    names = BUNDLED_BOLD_NAMES if style == "bold" else BUNDLED_REGULAR_NAMES
    for name in names:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    if _allow_system_font_fallback():
        for path in FONT_CANDIDATES[style]:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return ImageFont.load_default()


# ── Helpers ────────────────────────────────────────────────────────────────────

def download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return Image.open(BytesIO(resp.content)).convert("RGBA")


def build_gradient(size: tuple, fraction: float = 0.50) -> Image.Image:
    """
    Bottom-to-top black gradient covering `fraction` of the image height.
    Uses an exponential curve so the top edge of the gradient is invisible
    and the bottom is fully opaque.
    """
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    band  = int(h * fraction)
    start = h - band
    for y in range(band):
        t     = y / band                          # 0 → transparent, 1 → opaque
        alpha = int(255 * (t ** 1.2))
        draw.line([(0, start + y), (w, start + y)], fill=(0, 0, 0, alpha))
    return layer


def composite_bottom_scrim(
    img: Image.Image, scrim_top: int, alpha_max: int, steep: float = 2.35
) -> Image.Image:
    """Darken from scrim_top to bottom (inclusive)."""
    w, h = img.size
    scrim_top = max(0, min(scrim_top, h))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    for row in range(scrim_top, h):
        t = (row - scrim_top) / max(1, h - scrim_top)
        alpha = int(alpha_max * min(1.0, t * steep))
        dr.line([(0, row), (w, row)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img, layer)


def text_width(font: ImageFont.FreeTypeFont, text: str) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def text_height(font: ImageFont.FreeTypeFont, text: str) -> int:
    bbox = font.getbbox(text)
    return bbox[3] - bbox[1]


# ── Rating colour scale (mirrors IMDb's green/amber/red convention) ────────────

def rating_bg_color(rating_str: str) -> tuple:
    """Return an RGB fill colour for a rating badge background."""
    try:
        r = float(rating_str)
    except ValueError:
        return (100, 100, 100)   # grey for unknown
    if r >= 7.5:
        return (29, 185, 84)     # #1DB954 — green
    if r >= 6.0:
        return (200, 155, 10)    # #C89B0A — amber
    return (196, 50, 40)         # #C43228 — red


# ── Drawing primitives ─────────────────────────────────────────────────────────

def draw_imdb_badge(draw: ImageDraw.ImageDraw,
                    x: int, y: int,
                    rating: str,
                    font_label: ImageFont.FreeTypeFont,
                    font_rating: ImageFont.FreeTypeFont) -> int:
    """
    Draws the IMDb-style badge row:
        [ IMDb ]  [ 8.3 ]
    Both tiles share the same pad_x/pad_y so padding looks even. The taller
    tile defines the row height; the shorter one is centred within it.
    Returns the total row height.
    """
    label        = "IMDb"
    pad_x, pad_y = 8, 5
    gap          = 8

    # ── Measure both tiles ────────────────────────────────────────────────────
    lb = font_label.getbbox(label)
    lw, lh  = lb[2] - lb[0], lb[3] - lb[1]
    badge_w = lw + pad_x * 2
    badge_h = lh + pad_y * 2

    rb = font_rating.getbbox(rating)
    rw, rh  = rb[2] - rb[0], rb[3] - rb[1]
    tile_w  = rw + pad_x * 2
    tile_h  = rh + pad_y * 2

    # Row height is the taller of the two; each tile is centred within it
    row_h   = max(badge_h, tile_h)

    # ── IMDb yellow tile ──────────────────────────────────────────────────────
    imdb_y = y + (row_h - badge_h) // 2
    draw.rounded_rectangle(
        [x, imdb_y, x + badge_w, imdb_y + badge_h],
        radius=4,
        fill=IMDB_YELLOW,
    )
    draw.text(
        (x + pad_x - lb[0], imdb_y + pad_y - lb[1]),
        label, font=font_label, fill=IMDB_BLACK,
    )

    # ── Coloured rating tile ──────────────────────────────────────────────────
    tile_x = x + badge_w + gap
    tile_y = y + (row_h - tile_h) // 2
    draw.rounded_rectangle(
        [tile_x, tile_y, tile_x + tile_w, tile_y + tile_h],
        radius=4,
        fill=rating_bg_color(rating),
    )
    draw.text(
        (tile_x + pad_x - rb[0], tile_y + pad_y - rb[1]),
        rating, font=font_rating, fill=WHITE,
    )

    return row_h


def draw_genre_pills(draw: ImageDraw.ImageDraw,
                     genres: list,
                     x: int, y: int,
                     font: ImageFont.FreeTypeFont,
                     max_genres: int = 3) -> int:
    """
    Draws outlined yellow genre pills inline.
    All pills share the same height (computed from a cap-height reference) so
    padding is visually uniform regardless of which letters appear in each genre.
    Returns the pill height.
    """
    px, py   = 12, 6
    gap      = 8

    # Fix reference height from a string with cap letters + descenders so every
    # pill is the same height; avoids per-genre size jitter.
    ref_bbox = font.getbbox("Xy")
    ref_h    = ref_bbox[3] - ref_bbox[1]
    pill_h   = ref_h + py * 2

    cursor_x = x
    for genre in genres[:max_genres]:
        g_bbox = font.getbbox(genre)
        g_w    = g_bbox[2] - g_bbox[0]
        pw     = g_w + px * 2

        draw.rounded_rectangle(
            [cursor_x, y, cursor_x + pw, y + pill_h],
            radius=pill_h // 2,
            outline=IMDB_YELLOW,
            width=2,
        )
        # Offset by bbox[0]/[1] so the ink sits exactly px/py inside the pill
        draw.text(
            (cursor_x + px - g_bbox[0], y + py - g_bbox[1]),
            genre, font=font, fill=IMDB_YELLOW,
        )
        cursor_x += pw + gap

    return pill_h


def draw_title(draw: ImageDraw.ImageDraw,
               title: str, year: str,
               x: int, bottom_y: int,
               font_title: ImageFont.FreeTypeFont,
               font_year:  ImageFont.FreeTypeFont,
               max_width: int) -> int:
    """
    Draws title (wraps if needed) + year in grey.
    Text block grows upward: bottom of the last line is at bottom_y.
    Returns the y of the top edge of the title block.
    """
    avg_char_w = text_width(font_title, "W")
    max_chars  = max(8, max_width // avg_char_w)
    lines      = textwrap.wrap(title, width=max_chars) or [title]
    line_h     = text_height(font_title, "Ag") + 6

    # Draw lines upward: line[-1] (last line) has its top at bottom_y - line_h
    for i, line in enumerate(reversed(lines)):
        ly = bottom_y - (i + 1) * line_h
        draw.text((x, ly), line, font=font_title, fill=WHITE)

    top_y = bottom_y - len(lines) * line_h

    # Year — right of the last (bottom) line, vertically centered with it
    year_str      = f"  ({year})"
    last_line_top = bottom_y - line_h
    year_x        = x + text_width(font_title, lines[-1])
    year_top      = last_line_top + (line_h - text_height(font_year, year_str)) // 2
    draw.text((year_x, year_top), year_str, font=font_year, fill=GREY_LIGHT)

    return top_y


# ── Cover card (story-style bottom text stack) ───────────────────────────────

def draw_cover_cta_line(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y_base: int,
    line_h: int,
    f_text: ImageFont.FreeTypeFont,
    f_emoji: Optional[ImageFont.FreeTypeFont],
    fill: tuple,
    stroke_width: int = 0,
    stroke_fill: Optional[tuple] = None,
) -> None:
    kw = {}
    if stroke_width > 0 and stroke_fill is not None:
        kw = {"stroke_width": stroke_width, "stroke_fill": stroke_fill}
    if f_emoji:
        bb_t = f_text.getbbox(COVER_BODY_CTA_TEXT)
        h_t = bb_t[3] - bb_t[1]
        bb_e = f_emoji.getbbox(COVER_BODY_CTA_EMOJI)
        h_e = bb_e[3] - bb_e[1]
        y_t = y_base + (line_h - h_t) // 2
        y_e = y_base + (line_h - h_e) // 2
        draw.text(
            (x0 - bb_t[0], y_t - bb_t[1]),
            COVER_BODY_CTA_TEXT,
            font=f_text,
            fill=fill,
            **kw,
        )
        xe = x0 + text_width(f_text, COVER_BODY_CTA_TEXT)
        draw.text((xe - bb_e[0], y_e - bb_e[1]), COVER_BODY_CTA_EMOJI, font=f_emoji, fill=fill)
        return
    bb = f_text.getbbox(COVER_BODY_LINE3)
    ink_h = bb[3] - bb[1]
    yt = y_base + (line_h - ink_h) // 2
    draw.text((x0 - bb[0], yt - bb[1]), COVER_BODY_LINE3, font=f_text, fill=fill, **kw)


def cover_cta_line_height(
    f_text: ImageFont.FreeTypeFont,
    f_emoji: Optional[ImageFont.FreeTypeFont],
) -> int:
    if f_emoji:
        return max(
            text_height(f_text, COVER_BODY_CTA_TEXT),
            text_height(f_emoji, COVER_BODY_CTA_EMOJI),
        )
    return text_height(f_text, COVER_BODY_LINE3)


def render_cover_card(img: Image.Image, args) -> Image.Image:
    w, h = img.size
    m = int(min(w, h) * 0.055)
    x0 = m

    gradient = build_gradient((w, h), fraction=COVER_GRADIENT_FRACTION)
    img = Image.alpha_composite(img, gradient)

    img = composite_bottom_scrim(
        img, int(h * COVER_SCRIM_START_FRAC), COVER_SCRIM_ALPHA_MAX, steep=2.35
    )
    draw = ImageDraw.Draw(img)

    f_body = resolve_font("regular", max(int(h * 0.030), 15))
    f_cta = resolve_font("regular", max(int(h * 0.024), 12))
    f_cta_emoji = resolve_emoji_font(max(int(h * 0.028), 14))

    gap_body = max(int(h * 0.012), 6)

    h_cta = cover_cta_line_height(f_cta, f_cta_emoji)
    h_l2 = text_height(f_body, COVER_BODY_LINE2)
    h_l1 = text_height(f_body, COVER_BODY_LINE1)

    y = h - m
    y -= h_cta
    body_sw = max(1, getattr(f_body, "size", 16) // 28)
    cta_sw = max(1, getattr(f_cta, "size", 12) // 24)
    draw_cover_cta_line(
        draw,
        x0,
        y,
        h_cta,
        f_cta,
        f_cta_emoji,
        COVER_TEXT_SECONDARY,
        stroke_width=cta_sw,
        stroke_fill=COVER_TEXT_SHADOW,
    )

    y -= gap_body + h_l2
    bb = f_body.getbbox(COVER_BODY_LINE2)
    draw.text(
        (x0 - bb[0], y - bb[1]),
        COVER_BODY_LINE2,
        font=f_body,
        fill=COVER_TEXT_PRIMARY,
        stroke_width=body_sw,
        stroke_fill=COVER_TEXT_SHADOW,
    )

    y -= gap_body + h_l1
    bb = f_body.getbbox(COVER_BODY_LINE1)
    draw.text(
        (x0 - bb[0], y - bb[1]),
        COVER_BODY_LINE1,
        font=f_body,
        fill=COVER_TEXT_PRIMARY,
        stroke_width=body_sw,
        stroke_fill=COVER_TEXT_SHADOW,
    )

    return img


# ── IMDb overlay (full pipeline on downloaded poster) ─────────────────────────

def render_imdb_overlay(img: Image.Image, args, genres: list) -> Image.Image:
    w, h = img.size
    scale = w / 500.0

    f_title = resolve_font("bold", int(30 * scale))
    f_year = resolve_font("regular", int(18 * scale))
    f_badge = resolve_font("bold", int(17 * scale))
    f_rating = resolve_font("bold", int(26 * scale))
    f_genre = resolve_font("regular", int(15 * scale))

    gradient = build_gradient((w, h), fraction=0.65)
    img = Image.alpha_composite(img, gradient)

    margin = int(22 * scale)
    max_text_w = w - margin * 2
    bottom = h - margin

    _pad_y = 5
    _label_h = text_height(f_badge, "IMDb")
    _rating_h = text_height(f_rating, "0")
    badge_h_approx = max(_label_h, _rating_h) + _pad_y * 2
    badge_y = bottom - badge_h_approx

    gap_badge_title = int(14 * scale)
    title_bottom = badge_y - gap_badge_title

    avg_char_w = text_width(f_title, "W")
    max_chars = max(8, max_text_w // avg_char_w)
    title_lines = textwrap.wrap(args.title, width=max_chars) or [args.title]
    line_h = text_height(f_title, "Ag") + 6
    title_top = title_bottom - len(title_lines) * line_h

    gap_title_pills = int(12 * scale)
    pill_h_approx = text_height(f_genre, "M") + 10
    pill_y = title_top - gap_title_pills - pill_h_approx

    scrim_top = pill_y - int(12 * scale)
    img = composite_bottom_scrim(img, scrim_top, alpha_max=195, steep=2.2)
    draw = ImageDraw.Draw(img)

    draw_imdb_badge(
        draw,
        x=margin,
        y=badge_y,
        rating=args.rating,
        font_label=f_badge,
        font_rating=f_rating,
    )

    draw_title(
        draw,
        title=args.title,
        year=args.year,
        x=margin,
        bottom_y=title_bottom,
        font_title=f_title,
        font_year=f_year,
        max_width=max_text_w,
    )

    draw_genre_pills(
        draw,
        genres=genres,
        x=margin,
        y=pill_y,
        font=f_genre,
    )
    return img


# ── Storage upload ─────────────────────────────────────────────────────────────

def _upload_s3(local_path: str, s3_key: str, bucket: str, region: str) -> str:
    """Upload to AWS S3. Returns the public URL."""
    client = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )
    client.upload_file(
        local_path, bucket, s3_key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )
    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"


def _upload_r2(local_path: str, s3_key: str) -> str:
    """Upload to Cloudflare R2 (S3-compatible). Returns the public URL."""
    account_id  = os.environ.get("CF_R2_ACCOUNT_ID")
    access_key  = os.environ.get("CF_R2_ACCESS_KEY_ID")
    secret_key  = os.environ.get("CF_R2_SECRET_ACCESS_KEY")
    bucket      = os.environ.get("CF_R2_BUCKET")
    public_base = os.environ.get("CF_R2_PUBLIC_URL_BASE", "").rstrip("/")

    missing = [k for k, v in {
        "CF_R2_ACCOUNT_ID": account_id,
        "CF_R2_ACCESS_KEY_ID": access_key,
        "CF_R2_SECRET_ACCESS_KEY": secret_key,
        "CF_R2_BUCKET": bucket,
    }.items() if not v]
    if missing:
        sys.exit(f"R2 upload requires these env vars: {', '.join(missing)}")

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.upload_file(
        local_path, bucket, s3_key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )
    if public_base:
        return f"{public_base}/{s3_key}"
    return f"https://{bucket}.{account_id}.r2.cloudflarestorage.com/{s3_key}"


def upload_image(local_path: str, s3_key: str, provider: str,
                 s3_bucket: Optional[str] = None, s3_region: Optional[str] = None) -> str:
    """
    Upload `local_path` to the chosen storage provider.
    provider: 's3' or 'r2'
    Returns the public URL.
    """
    if provider == "r2":
        return _upload_r2(local_path, s3_key)

    # Default: AWS S3
    bucket = s3_bucket or os.environ.get("S3_BUCKET")
    region = s3_region or os.environ.get("S3_REGION")
    if not bucket or not region:
        sys.exit("S3 upload requires S3_BUCKET and S3_REGION (env or --s3-bucket / --s3-region)")
    return _upload_s3(local_path, s3_key, bucket, region)


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Add IMDB-styled overlay or cover card to movie poster")
    p.add_argument(
        "--image-type",
        choices=("imdb", "cover"),
        default="imdb",
        help="imdb: rating badge + genres; cover: story-style text stack at bottom",
    )
    p.add_argument("--input", required=True, help="TMDB image URL")
    p.add_argument("--rating", default=None, help="IMDB rating (required for --image-type imdb)")
    p.add_argument("--title", required=True, help="Movie title")
    p.add_argument("--genres", default=None, help="Comma-separated genres (required for --image-type imdb)")
    p.add_argument("--year", default=None, help="Release year (required for --image-type imdb)")
    p.add_argument("--movie-id", required=True, help="TMDB movie ID (used for S3 key)")
    p.add_argument("--output", required=True, help="Local output path, e.g. /tmp/n8n-movies/123.jpg")
    p.add_argument("--s3-bucket", default=None, help="S3 bucket name (overrides S3_BUCKET env var)")
    p.add_argument("--s3-region", default=None, help="AWS region (overrides S3_REGION env var)")
    p.add_argument(
        "--storage",
        choices=("s3", "r2"),
        default=None,
        help="Storage provider: s3 (AWS) or r2 (Cloudflare). Overrides STORAGE_PROVIDER env var.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    if args.image_type == "imdb":
        if args.rating is None or args.genres is None or args.year is None:
            sys.exit("imdb mode requires --rating, --genres, and --year")
        genres = [g.strip() for g in args.genres.split(",") if g.strip()]
    else:
        genres = []

    img = download_image(args.input)
    if args.image_type == "cover":
        img = render_cover_card(img, args)
    else:
        img = render_imdb_overlay(img, args, genres)

    # ── 7. Save locally ───────────────────────────────────────────────────────
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    out_img = img.convert("RGB")
    out_img.save(args.output, "JPEG", quality=95, optimize=True)

    # ── 8. Upload ─────────────────────────────────────────────────────────────
    provider   = args.storage or os.environ.get("STORAGE_PROVIDER", "s3")
    s3_key     = f"movie-overlays/{args.movie_id}_overlay.jpg"
    public_url = upload_image(
        args.output, s3_key, provider,
        s3_bucket=args.s3_bucket,
        s3_region=args.s3_region,
    )

    # ── 9. Print URL to stdout (n8n reads this) ───────────────────────────────
    print(public_url)


if __name__ == "__main__":
    main()