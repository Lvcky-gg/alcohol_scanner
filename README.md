# Flask API + Local Postgres (Docker)

This project runs a Flask API locally and Postgres in Docker.

It includes OCR + rule-based verification for alcohol label fields:

- Single-label verification
- Batch verification (up to 300 files per request)
- Strict government warning validation
- Fuzzy matching for fields like brand and class/type to reduce false mismatches

## 1) Prerequisites

- Python 3.10+ < 3.13
- Docker + Docker Compose
- Linux system libs for OCR (if missing): `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`

Compatibility note:

- PaddleOCR currently requires a supported Python runtime (recommended: 3.10-3.12)

## 2) Configure environment

```bash
cp .env.example .env
```


## 3) Create virtual environment and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate


pip install -r requirements-ocr.txt
```

If you need PaddleOCR on a machine using newer system Python (for example 3.14), use a dedicated Python 3.12 env:

```bash
uv python install 3.12
uv venv --python 3.12 --seed .venv-ocr
uv pip install --python .venv-ocr/bin/python -r requirements-ocr.txt
```

## 4) Run Flask API locally

```bash
python app.py
```

For OCR-enabled runtime, launch with the OCR env interpreter:

```bash
source .venv-ocr/bin/activate
python app.py
```

API will start on http://localhost:5000

## Run With Docker (Frontend + Backend)


```bash
docker compose up --build
```

Services:

- Frontend: http://localhost:8080
- Backend API: http://localhost:5000

If Ollama is running on your host and backend runs in Docker, this compose file maps host access automatically via `host.docker.internal`.

Stop containers:

```bash
docker compose down
```


## Dev Docker Compose


```bash
docker compose -f docker-compose.dev.yml up --build
```

Services:

- Frontend: http://localhost:8080
- Backend API: http://localhost:5000

The frontend proxies `/api/*` requests to the backend container, so browser requests from `http://localhost:8080` work without extra CORS setup.



Stop dev stack:

```bash
docker compose -f docker-compose.dev.yml down
```

## 5) Test endpoints

```bash
curl http://localhost:5000/health

# OCR: send an image file as multipart form-data
curl -X POST http://localhost:5000/ocr \
	-F "file=@/absolute/path/to/image.png"

# Requirements metadata
curl http://localhost:5000/requirements

# Single verification
curl -X POST http://localhost:5000/verify \
	-F "file=@/absolute/path/to/label.png" \
	-F 'application={
		"brand_name":"OLD TOM DISTILLERY",
		"class_type":"Kentucky Straight Bourbon Whiskey",
		"alcohol_content":"45% Alc./Vol. (90 Proof)",
		"net_contents":"750 mL",
		"name_address":"Old Tom Distillery, Louisville, KY",
		"country_of_origin":"United States"
	}'

# Verification with Ollama additional inference
curl -X POST http://localhost:5000/verify/ollama \
	-F "file=@/absolute/path/to/label.png" \
	-F 'application={
		"brand_name":"OLD TOM DISTILLERY",
		"class_type":"Kentucky Straight Bourbon Whiskey",
		"alcohol_content":"45% Alc./Vol. (90 Proof)",
		"net_contents":"750 mL"
	}'

# Batch verification (files matched by filename first, then by list index)
curl -X POST http://localhost:5000/verify/batch \
	-F "files=@/absolute/path/to/label-1.png" \
	-F "files=@/absolute/path/to/label-2.png" \
	-F 'applications=[
		{
			"filename":"label-1.png",
			"brand_name":"OLD TOM DISTILLERY",
			"class_type":"Kentucky Straight Bourbon Whiskey",
			"alcohol_content":"45% Alc./Vol. (90 Proof)",
			"net_contents":"750 mL"
		},
		{
			"filename":"label-2.png",
			"brand_name":"STONE'S THROW",
			"class_type":"American Gin",
			"alcohol_content":"40% Alc./Vol.",
			"net_contents":"1 L"
		}
	]'
```

## Notes

- Postgres connectivity uses `pg8000` (pure Python) to avoid native `psycopg2` build failures
- OCR settings are configured with `OCR_LANG` and `OCR_USE_GPU`
- OCR tuning options: `OCR_ENHANCE`, `OCR_UPSCALE_FACTOR`, `OCR_MULTI_PASS`, `OCR_SHOW_LOG`
- Ollama settings: `OLLAMA_ENABLED`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_PROMPT_PATH`
- On unsupported Python versions for PaddleOCR, `/ocr`, `/verify`, and `/verify/batch` return a clear dependency message
- The government warning check is strict and expects uppercase canonical text
- "bold" text validation is not possible with OCR-only text extraction in this prototype

## Ollama Verification

The endpoint `POST /verify/ollama` adds LLM-based inference on top of OCR + rule checks.

- It reads your prompt template from `prompts/ollama_inference_prompt.txt`
- It replaces `{{OCR_RESPONSE_JSON}}` with live OCR payload
- It calls Ollama `/api/generate` and parses JSON output

Run Ollama first (example):

```bash
ollama serve
ollama pull llama3.1:8b
```

## OCR Tuning

If bottle images are hard to read (glare, small text, curved labels), tune these `.env` values:

- `OCR_ENHANCE=true`: run extra pre-processing variants (denoise/threshold/sharpen)
- `OCR_UPSCALE_FACTOR=2.0`: upscale before OCR; try `2.5` or `3.0` for very small text
- `OCR_MULTI_PASS=true`: run both classifier and non-classifier OCR passes
- `OCR_SHOW_LOG=false`: set `true` for Paddle debug logs
- `OCR_ISOLATE_PROCESS=true`: run OCR in a worker process so native crashes do not kill Flask
- `OCR_WORKER_TIMEOUT_SECONDS=60`: max seconds before worker is aborted
- `OCR_CROP_PASSES=true`: run focused passes over likely label regions
- `OCR_DET_LIMIT_SIDE_LEN=1536`: larger detection side length helps tiny text
- `OCR_DET_DB_BOX_THRESH=0.30`: lower box threshold to keep weak detections
- `OCR_DET_DB_THRESH=0.25`: lower DB threshold for faint text
- `OCR_REC_SCORE_THRESH=0.0`: keep low-confidence text for downstream verification review
- `OCR_MIN_LINE_CHARS=2`: filter very short OCR noise

For maximum stability on Linux native stack issues, keep:

- `OCR_ISOLATE_PROCESS=true`
- `OCR_ENHANCE=false`

For better bottle-label recall, try this baseline:

- `OCR_CROP_PASSES=true`
- `OCR_UPSCALE_FACTOR=2.5`
- `OCR_DET_LIMIT_SIDE_LEN=1920`
- `OCR_DET_DB_BOX_THRESH=0.25`
- `OCR_DET_DB_THRESH=0.20`

## Verification Rules

- `brand_name`, `class_type`, `name_address`, `country_of_origin`: fuzzy matching (`pass`, `review`, `fail`)
- `alcohol_content`, `net_contents`: normalized exact matching
- `government_warning`: strict exact match against required uppercase statement

## API Response Shape

- `overall_status`: `pass` | `review` | `fail`
- `checks`: array of per-field decisions with expected, detected, score, and reason
- `ocr_line_count`: number of OCR lines read from the image

OCR endpoints also return extracted structured fields:

```json
{
	"fields": {
		"brandName": "...",
		"classType": "...",
		"class/type": "...",
		"alcoholContent": "...",
		"netContents": "...",
		"countryOfOrigin": "...",
		"producer": "..."
	}
}
```
