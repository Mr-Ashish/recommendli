#!/usr/bin/env python3
"""
overlay.py  —  IMDB-themed movie poster overlay
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
"""

import argparse
import os
import sys
import textwrap
import requests
import boto3
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ── IMDB brand colours ─────────────────────────────────────────────────────────
IMDB_YELLOW   = (245, 197, 24)       # #F5C518
IMDB_BLACK    = (0,   0,   0)
WHITE         = (255, 255, 255)
GREY_LIGHT    = (180, 180, 180)
OVERLAY_BLACK = (0,   0,   0, 210)   # semi-transparent for gradient

# ── Font resolution (tries system paths, falls back to PIL default) ─────────────
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

def resolve_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES[style]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
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


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Add IMDB-styled overlay to movie poster")
    p.add_argument("--input",     required=True,  help="TMDB image URL")
    p.add_argument("--rating",    required=True,  help="IMDB rating, e.g. 8.3")
    p.add_argument("--title",     required=True,  help="Movie title")
    p.add_argument("--genres",    required=True,  help="Comma-separated genre list")
    p.add_argument("--year",      required=True,  help="Release year")
    p.add_argument("--movie-id",  required=True,  help="TMDB movie ID (used for S3 key)")
    p.add_argument("--output",    required=True,  help="Local output path, e.g. /tmp/n8n-movies/123.jpg")
    p.add_argument("--s3-bucket", required=True,  help="S3 bucket name")
    p.add_argument("--s3-region", required=True,  help="AWS region, e.g. ap-south-1")
    return p.parse_args()


def main():
    args   = parse_args()
    genres = [g.strip() for g in args.genres.split(",") if g.strip()]

    # ── 1. Download poster ────────────────────────────────────────────────────
    img    = download_image(args.input)
    w, h   = img.size
    scale  = w / 500.0          # normalise relative to 500 px wide reference

    # ── 2. Font sizes (scale with poster width) ───────────────────────────────
    f_title  = resolve_font("bold",    int(30 * scale))
    f_year   = resolve_font("regular", int(18 * scale))
    f_badge  = resolve_font("bold",    int(17 * scale))   # "IMDb" label
    f_rating = resolve_font("bold",    int(26 * scale))   # big rating number
    f_genre  = resolve_font("regular", int(15 * scale))   # pill text

    # ── 3. Gradient overlay ───────────────────────────────────────────────────
    gradient = build_gradient((w, h), fraction=0.65)
    img      = Image.alpha_composite(img, gradient)

    margin     = int(22 * scale)
    max_text_w = w - margin * 2
    bottom     = h - margin

    # ── Pre-compute layout positions (bottom-up) ──────────────────────────────
    # row_h mirrors draw_imdb_badge: max of both tile heights (pad_y=5 each)
    _pad_y          = 5
    _label_h        = text_height(f_badge,  "IMDb")
    _rating_h       = text_height(f_rating, "0")
    badge_h_approx  = max(_label_h, _rating_h) + _pad_y * 2
    badge_y         = bottom - badge_h_approx

    gap_badge_title = int(14 * scale)
    title_bottom    = badge_y - gap_badge_title

    avg_char_w  = text_width(f_title, "W")
    max_chars   = max(8, max_text_w // avg_char_w)
    title_lines = textwrap.wrap(args.title, width=max_chars) or [args.title]
    line_h      = text_height(f_title, "Ag") + 6
    title_top   = title_bottom - len(title_lines) * line_h

    gap_title_pills = int(12 * scale)
    pill_h_approx   = text_height(f_genre, "M") + 10   # py=5 each side
    pill_y          = title_top - gap_title_pills - pill_h_approx

    # ── 4. Dark scrim behind the text block (ensures readability) ────────────
    scrim_top   = pill_y - int(12 * scale)
    scrim_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    scrim_draw  = ImageDraw.Draw(scrim_layer)
    for row in range(scrim_top, h):
        t     = (row - scrim_top) / max(1, h - scrim_top)
        alpha = int(195 * min(1.0, t * 2.2))
        scrim_draw.line([(0, row), (w, row)], fill=(0, 0, 0, alpha))
    img  = Image.alpha_composite(img, scrim_layer)
    draw = ImageDraw.Draw(img)

    # ── 5. IMDB badge  (bottom edge flush with bottom margin) ────────────────
    draw_imdb_badge(
        draw,
        x          = margin,
        y          = badge_y,
        rating     = args.rating,
        font_label = f_badge,
        font_rating= f_rating,
    )

    # ── 6. Title + year  (bottom of title block at title_bottom) ─────────────
    draw_title(
        draw,
        title      = args.title,
        year       = args.year,
        x          = margin,
        bottom_y   = title_bottom,
        font_title = f_title,
        font_year  = f_year,
        max_width  = max_text_w,
    )

    # ── 7. Genre pills  (top of pill block at pill_y) ────────────────────────
    draw_genre_pills(
        draw,
        genres  = genres,
        x       = margin,
        y       = pill_y,
        font    = f_genre,
    )

    # ── 7. Save locally ───────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    out_img = img.convert("RGB")
    out_img.save(args.output, "JPEG", quality=95, optimize=True)

    # ── 8. Upload to S3 ───────────────────────────────────────────────────────
    # s3_key = f"movie-overlays/{args.movie_id}_overlay.jpg"
    # s3     = boto3.client("s3", region_name=args.s3_region)

    # s3.upload_file(
    #     args.output,
    #     args.s3_bucket,
    #     s3_key,
    #     ExtraArgs={
    #         "ContentType": "image/jpeg",
    #         "ACL":         "public-read",
    #     },
    # )

    # public_url = (
    #     f"https://{args.s3_bucket}.s3.{args.s3_region}.amazonaws.com/{s3_key}"
    # )

    # ── 9. Print URL to stdout (n8n reads this) ───────────────────────────────
    # print(public_url)


if __name__ == "__main__":
    main()