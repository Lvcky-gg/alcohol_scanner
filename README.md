# Flask API + Frontend

This project runs a Flask API and frontend in Docker.

It includes OCR + rule-based verification for alcohol label fields:

- Single-label verification
- Batch verification (up to 300 files per request)
- Strict government warning validation
- Fuzzy matching for fields like brand and class/type to reduce false mismatches

## Quickstart Guide
- run ollama
```bash
ollama serve
ollama pull llama3.1:8b
```
- cp .env.example .env
- docker compose up

## Engineering Decisions

### Two-stage verification pipeline
Rule-based checks run first on every request. Ollama LLM inference runs second on `/verify/ollama` only. This keeps the cheap path fast and the expensive path optional. Rule results take precedence in the merged output; Ollama fills gaps when OCR alone is insufficient.

### Strict government warning, fuzzy everything else
The government warning uses exact uppercase string matching against the canonical TTB-required text. Any deviation is a fail with score 0. All other fields (`brand_name`, `class_type`, `name_address`, `country_of_origin`) use rapidfuzz token ratio matching so minor OCR noise and spelling variations produce `review` rather than a hard fail. `alcohol_content` and `net_contents` use normalized exact matching (unit normalization, whitespace stripping) as a middle ground.

### PaddleOCR in a separate Python 3.12 venv
PaddleOCR requires Python 3.10–3.12 and has native C++ dependencies that conflict with newer system Pythons. The core API is kept dependency-light and runs on any Python version. OCR is installed in a separate `.venv-ocr` environment and imported at runtime; if it is missing the endpoints return a clear error instead of crashing.

### OCR worker process isolation
Setting `OCR_ISOLATE_PROCESS=true` runs each OCR call in a subprocess so native paddle/OpenCV crashes do not kill the Flask process. The worker communicates via stdout JSON and is killed after `OCR_WORKER_TIMEOUT_SECONDS`. This trades latency for stability on bottle images with unusual formats.

### Backend on host network mode in Docker
The backend container uses `network_mode: host` so it can reach Ollama on `localhost:11434` without any bridge routing. Ollama binds to `127.0.0.1` only, which is unreachable from a bridged container via `host.docker.internal` on Linux. Host networking eliminates the workaround entirely.


### Batch matching by filename then index
When batch-verifying, applications are matched to uploaded files by filename first. If no filename match is found, the application at the same list index is used as a fallback. This lets callers omit filenames for simple ordered batches while supporting named matching for arbitrarily ordered uploads.

### VITE_API_BASE_URL as a build arg
The API base URL is baked into the frontend bundle at build time via a Vite env variable passed as a Docker build arg. In the Docker stack it is set to `/api` so all requests are relative and proxied by nginx/Caddy. In raw `npm run dev` it falls back to `http://localhost:5000` via the Vite dev server proxy configured in `vite.config.ts`.

### Local Hosting
I am hosting everything on my own silicon; inlcuding the models, API, and frontend. I have functional infrastucture for something like this and would prefer to avoid the use of tokens and cloud hosting fees when not necessary
This does require workarounds on ports given that 80 and 443 are blocked by my ISP. Please note that this means i am cold starting the models periodically in order to maintain uptime with a systemD timer. Users may experience some longer upload times periodically
I also think its worth exploring this kind of thing for actual products with lower ammounts of users. Although I have an old GPU that makes things slow, you can speed things up on higher end equipment and edge deployment strategies


### Public Cost Stewardship
- Default to cheapest viable path: rules first, OCR second, LLM last.
- Keep local model support to avoid mandatory per-request vendor charges.
- Expose tunable runtime controls (`OCR_*`, `OLLAMA_*`) so operators can trade latency, quality, and cost without code changes.
- Prefer open-source and portable components (Flask, Caddy, Nginx, Docker) to reduce lock-in and procurement risk.
- Maintain deterministic, auditable outputs (`checks`, `overall_status`, canonical warning policy) suitable for governance review.
- Batch endpoint support (up to 300 files) amortizes overhead and reduces per-label processing cost.

### The Correct Solution
The correct solution is a mobile app connected to APIs. I imagine the UI would be similar to old QR scanners, where the user could scan the label. It would then hit an API(I would prefer if we used Rust for this one) that either hits APIs based on token use or local infrastructure. I would only encourage using the tokens 
if you are willing to budget for it and you don't have infrastructure in place or if the user count is very low. Either way, this becomes a fast solution and could hit near real time detection

### A Better Solution Than Mine
Would use better hardware (I am on an arch linux box with relatively low specs so I can't host the fastest models) and/or would hit anthropic/openai/etc apis rather than local models. I would still generally approach things in the same way. My current solution is very good for cost effectiveness however.

## 1) Prerequisites

- Python 3.10+ < 3.13
- Docker + Docker Compose
- Linux system libs for OCR (if missing): `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`
- Locally running ollama instance

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

---

## API Reference

Base URL: `http://localhost:5000` (dev) or `https://tactical.johnodonnell.xyz` (prod)

All file uploads use `multipart/form-data`. All responses are JSON.

---

### `GET /health`

Returns service health status.

**Response `200`**
```json
{ "status": "ok" }
```

---


### `GET /requirements`

Returns required label fields and the canonical government warning text.

**Response `200`**
```json
{
  "required_fields": ["brand_name", "class_type", "alcohol_content", "net_contents", "name_address", "country_of_origin", "government_warning"],
  "standard_government_warning": "GOVERNMENT WARNING: ..."
}
```

---

### `POST /ocr`

Runs OCR on an uploaded label image and returns raw lines and extracted fields.

**Request** `multipart/form-data`
| Field | Type | Required |
|-------|------|----------|
| `file` | image file | Yes |

**Response `200`**
```json
{
  "line_count": 42,
  "lines": ["LINE ONE", "LINE TWO"],
  "fields": {
    "brandName": "...",
    "classType": "...",
    "alcoholContent": "...",
    "netContents": "...",
    "countryOfOrigin": "...",
    "producer": "..."
  }
}
```

---

### `POST /verify`

Runs OCR + rule-based field verification against a submitted application.

**Request** `multipart/form-data`
| Field | Type | Required |
|-------|------|----------|
| `file` | image file | Yes |
| `application` | JSON string | No |

**`application` fields** (all optional; government warning always checked against canonical):
```json
{
  "brand_name": "OLD TOM DISTILLERY",
  "class_type": "Kentucky Straight Bourbon Whiskey",
  "alcohol_content": "45% Alc./Vol. (90 Proof)",
  "net_contents": "750 mL",
  "name_address": "Old Tom Distillery, Louisville, KY",
  "country_of_origin": "United States"
}
```

**Response `200`**
```json
{
  "overall_status": "pass",
  "checks": [
    {
      "field": "brand_name",
      "expected": "OLD TOM DISTILLERY",
      "detected": "OLD TOM DISTILLERY",
      "score": 100.0,
      "status": "pass",
      "reason": "..."
    }
  ],
  "ocr_line_count": 42,
  "fields": { "brandName": "...", "classType": "..." },
  "filename": "label.png",
  "processing_target_seconds": 5
}
```

---

### `POST /verify/ollama`

Runs OCR + rule verification + Ollama LLM inference. Returns merged canonical fields and full breakdown.

**Request** `multipart/form-data` — same fields as `/verify`

**Response `200`**
```json
{
  "filename": "label.png",
  "line_count": 42,
  "lines": ["..."],
  "fields": { "brandName": "...", "classType": "..." },
  "finalFields": { "brandName": "...", "classType": "..." },
  "canonicalFields": {
    "brandName": "...",
    "classType": "...",
    "alcoholContent": "...",
    "netContents": "...",
    "countryOfOrigin": "...",
    "producer": "..."
  },
  "ruleVerification": {
    "overall_status": "pass",
    "checks": [],
    "ocr_line_count": 42
  },
  "ollamaVerification": {
    "enabled": true,
    "error": null,
    "model": "llama3.1:8b",
    "parsed": {
      "brandName": "...",
      "governmentWarningPresent": true,
      "governmentWarningValid": true,
      "confidence": { "brandName": 0.95, "governmentWarning": 0.9 },
      "evidence": { "brandName": ["RAW OCR LINE"] }
    },
    "raw": "..."
  }
}
```

---

### `POST /verify/ollama/canonical`

Same as `/verify/ollama` but returns only the merged canonical fields object.

**Response `200`**
```json
{
  "brandName": "...",
  "classType": "...",
  "alcoholContent": "...",
  "netContents": "...",
  "countryOfOrigin": "...",
  "producer": "..."
}
```

---

### `POST /verify/batch`

Runs rule-based verification on up to 300 label images in one request. Files are matched to applications by filename first, then by list index.

**Request** `multipart/form-data`
| Field | Type | Required |
|-------|------|----------|
| `files` | image files (repeat field) | Yes |
| `applications` | JSON array string | No |

**`applications` array:**
```json
[
  {
    "filename": "label-1.png",
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL"
  }
]
```

**Response `200`**
```json
{
  "summary": { "total": 2, "pass": 1, "review": 0, "fail": 1 },
  "results": [
    {
      "filename": "label-1.png",
      "overall_status": "pass",
      "checks": [],
      "ocr_line_count": 38,
      "fields": {}
    }
  ]
}
```

---

### Status values

| Value | Meaning |
|-------|---------|
| `pass` | Field matches expected with high confidence |
| `review` | Partial or low-confidence match; human review recommended |
| `fail` | Field missing or does not match |

### Error responses

All endpoints return `{ "error": "message" }` with an appropriate HTTP status code (`400`, `500`).

---