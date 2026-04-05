Bundled fonts (recommended — same output on every machine)
==========================================================

1. Create or use this folder: recommendli/fonts/  (next to image_creator.py)

2. Put your font family here: every .ttf / .otf under fonts/ (any subfolder) is
   picked up automatically. Files with "Bold", "SemiBold", "Black", etc. in the
   name are used for bold text; all other weights (Regular, Light, Italic, …)
   are used for regular text. If you only have one file (e.g. Margarine-Regular.ttf),
   it is used for BOTH bold and regular.

   Color emoji fonts are excluded from body text (matched by filename, e.g.
   NotoColorEmoji.ttf) so they are not picked as the main UI font.

3. If no font files are found, the script falls back to these fixed names (in order):

   Bold: bold.ttf, Inter-Bold.ttf, Inter_18pt-Bold.ttf, DejaVuSans-Bold.ttf
   Regular: regular.ttf, Inter-Regular.ttf, Inter_18pt-Regular.ttf, DejaVuSans.ttf

4. Optional — cover-mode CTA emojis: add NotoColorEmoji.ttf or emoji.ttf (see Google Noto Color Emoji).

5. Google Fonts (example — Inter):
   - Open https://fonts.google.com/specimen/Inter
   - Click "Get font" / Download
   - Unzip; under the static/ folder copy Inter-Bold.ttf and Inter-Regular.ttf
     into this fonts/ folder (you can rename to bold.ttf / regular.ttf if you like)

6. Override directory (optional):
   export RECOMMENDLI_FONTS_DIR=/path/to/your/font/folder

7. If no file is found in fonts/, the script falls back to system font paths
   (set RECOMMENDLI_ALLOW_SYSTEM_FONTS=0 to disable that fallback).

Check font licenses before redistributing TTF files with your app.
