# n8n Movie Pipeline — Setup Checklist

## 1. Python environment
```bash
cd /YOUR/PATH/n8n-movies
pip3 install -r requirements.txt

# Verify AWS credentials are configured (overlay.py uses boto3 default chain)
aws configure        # or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in env
```

## 1b. Bundled fonts (recommended)

The script prefers TTF files in the repo’s `fonts/` directory so output does not rely on OS fonts. See [`fonts/README.txt`](fonts/README.txt) for download links (e.g. Inter + optional Noto Color Emoji), exact filenames, `RECOMMENDLI_FONTS_DIR`, and `RECOMMENDLI_ALLOW_SYSTEM_FONTS`.

## 2. S3 bucket
```bash
# Create bucket (if not already done)
aws s3api create-bucket \
  --bucket YOUR_BUCKET_NAME \
  --region YOUR_AWS_REGION \
  --create-bucket-configuration LocationConstraint=YOUR_AWS_REGION

# Disable Block Public Access so public-read ACL works
aws s3api put-public-access-block \
  --bucket YOUR_BUCKET_NAME \
  --public-access-block-configuration \
    BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false
```

## 3. n8n credentials to create
Go to n8n → Settings → Credentials → New

| Name in workflow     | Type                  | What to fill in                                                       |
|----------------------|-----------------------|-----------------------------------------------------------------------|
| TMDB Bearer          | HTTP Header Auth      | Name: `Authorization`  Value: `Bearer YOUR_TMDB_READ_API_KEY`        |
| RapidAPI IMDB        | HTTP Header Auth      | Name: `X-RapidAPI-Key`  Value: `YOUR_RAPIDAPI_KEY`  + second header: `X-RapidAPI-Host` = `imdb236.p.rapidapi.com` |
| OpenAI               | OpenAI API            | Your OpenAI API key                                                   |
| Google Sheets        | Google Sheets OAuth2  | Follow n8n OAuth2 wizard                                              |

## 4. Edit workflow.json before importing
Replace these three strings everywhere they appear:

- `/YOUR/PATH/n8n-movies/overlay.py`  →  absolute path on your machine
- `YOUR_BUCKET_NAME`                  →  your S3 bucket name
- `YOUR_AWS_REGION`                   →  e.g. `ap-south-1`
- `YOUR_GOOGLE_SHEET_ID`              →  from the Sheet URL

## 5. Google Sheet columns (create in this order, row 1 = headers)
```
A: Timestamp
B: Theme
C: Movies (titles)
D: IMDB Ratings
E: Genres
F: S3 Image URLs
G: Caption
H: Instagram Media ID
I: Post Status
```

## 6. Test the Python script standalone
```bash
python3 overlay.py \
  --input    "https://image.tmdb.org/t/p/w780/qNBAXBIQlnOThrVvA6mA2B5ggV6.jpg" \
  --rating   "8.3" \
  --title    "Oppenheimer" \
  --genres   "History,Drama,Thriller" \
  --year     "2023" \
  --movie-id "872585" \
  --output   "/tmp/test_overlay.jpg" \
  --s3-bucket "YOUR_BUCKET_NAME" \
  --s3-region "YOUR_AWS_REGION"

# Should print the public S3 URL if everything is wired correctly
```

### Cover image type (`--image-type cover`)

Story-style bottom text (fixed copy + dynamic uppercase title). Does **not** use `--rating`, `--genres`, or `--year`. Uses the **same** S3 object key as IMDb mode (`movie-overlays/{movie_id}_overlay.jpg`).

```bash
python3 image_creator.py \
  --image-type cover \
  --input    "https://image.tmdb.org/t/p/w780/qNBAXBIQlnOThrVvA6mA2B5ggV6.jpg" \
  --title    "The Matrix" \
  --movie-id "603" \
  --output   "/tmp/test_cover.jpg" \
  --s3-bucket "YOUR_BUCKET_NAME" \
  --s3-region "YOUR_AWS_REGION"
```

Cover mode draws two teaser lines plus the swipe/CTA line (with emoji when a color emoji font is available). No movie title. Lighter bottom gradient than IMDb mode.

## 7. n8n Execute Command node — exact string
```
python3 /YOUR/PATH/n8n-movies/overlay.py \
  --input      "{{ $json.poster_url }}" \
  --rating     "{{ $json.imdb_rating }}" \
  --title      "{{ $json.title }}" \
  --genres     "{{ $json.genres }}" \
  --year       "{{ $json.release_year }}" \
  --movie-id   "{{ $json.tmdb_id }}" \
  --output     "/tmp/n8n-movies/{{ $json.tmdb_id }}_overlay.jpg" \
  --s3-bucket  "YOUR_BUCKET_NAME" \
  --s3-region  "YOUR_AWS_REGION"
```

## 8. Import workflow
n8n → Workflows → Import from file → select workflow.json
Then open each node and assign the credentials you created in step 3.

## Common issues
- **Font not found**: script falls back to PIL default; install dejavu-fonts-ttf on Ubuntu with `sudo apt install fonts-dejavu`
- **S3 403 on upload**: check Block Public Access settings (step 2) and IAM policy allows `s3:PutObject` + `s3:PutObjectAcl`
- **RapidAPI 401**: the second header `X-RapidAPI-Host` must be set in the credential — n8n's HTTP Header Auth only supports one header per credential, so use a Header Auth with a custom header JSON or use two separate credentials chained
- **TMDB returns no imdb_id**: some very new releases don't have an IMDB ID yet; the Code node guards this with `?? 'N/A'`