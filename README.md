# 🏦 FindLEI, LEI Batch Compliance Checker

> A production-grade B2B web application for banking compliance officers. Upload a client spreadsheet, verify every LEI against GLEIF and lei-lookup.com, and download the enriched file, with Entity Status and Next Renewal Date written back into Excel automatically.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker)](https://docker.com)
[![CI](https://img.shields.io/github/actions/workflow/status/ThanasisSoftwareDeveloper/Banks-L.E.I./ci.yml?style=flat-square&label=CI)](https://github.com/ThanasisSoftwareDeveloper/Banks-L.E.I./actions)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue?style=flat-square)](LICENSE)

---

## ✨ Features

- 📂 **Excel / LibreOffice Calc support** — upload `.xlsx`, `.ods`, or `.xls` client files
- 🔍 **Auto-detection** of the LEI column by header name or 20-character pattern
- ✅ **Dual-source lookup** — GLEIF official API first, lei-lookup.com as fallback
- 🎨 **Colour-coded output** — green (ACTIVE), red (INACTIVE/NOT FOUND) written back to Excel
- 📡 **Real-time progress** — Server-Sent Events stream with live per-LEI feed
- 🛡️ **Anti-blocking** — token-bucket rate limiter + exponential back-off per host
- 📊 **Observability** — Prometheus `/metrics` endpoint + structured JSON logs
- 🐳 **Containerised** — single `docker compose up` deployment

---
> **Note:** The current API specification supports up to **200 LEI codes per uploaded file**. Each document you upload is processed as a single batch run of up to 200 records.

## 🏗️ Architecture

```
Banks-L.E.I./
├── main.py               # FastAPI app — upload, process, SSE stream, download
├── lei_checker.py        # GLEIF API + lei-lookup.com fallback + batch processor
├── excel_handler.py      # openpyxl read/write with auto-column detection
├── rate_limiter.py       # Token-bucket rate limiter per host
├── log_config.py         # Structured JSON logging (prod) / human-readable (dev)
├── metrics.py            # Prometheus counters, histograms, gauges
├── static/
│   └── index.html        # Full frontend — single file, no build step
├── tests/
│   ├── conftest.py
│   ├── test_api.py           # FastAPI integration tests (9 tests)
│   ├── test_excel_handler.py # Excel read/write tests (11 tests)
│   ├── test_lei_checker.py   # LEI engine unit tests (16 tests)
│   └── test_rate_limiter.py  # Token bucket tests (6 tests)
├── .github/
│   └── workflows/
│       └── ci.yml        # Test → Security scan → Secret scan → Docker + SBOM
├── Dockerfile
└── docker-compose.yml
```

---

## 🚀 Setup

### Prerequisites

- **Python** 3.11+
- **Docker** + Docker Compose (for production deployment)

---

### 1. Clone the repo

```bash
git clone https://github.com/ThanasisSoftwareDeveloper/Banks-L.E.I..git findlei
cd findlei
```

---

### 2. Local development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run dev server
LOG_FORMAT=text uvicorn main:app --reload --port 8000
```

**App runs at:** `http://localhost:8000`
**API docs:** `http://localhost:8000/docs`
**Metrics:** `http://localhost:8000/metrics`
**Health:** `http://localhost:8000/health`

---

### 3. Run tests

```bash
LOG_FORMAT=text pytest -v
```

Output:
```
42 passed in 4.1s
```

---

### 4. Docker deployment

```bash
docker compose up -d --build
```

---

### 5. Production (findlei.com)

Nginx reverse proxy with SSL — see the full config in `README` under **Nginx** section. Key setting for SSE:

```nginx
proxy_buffering off;
proxy_read_timeout 300s;
```

---

## 📖 Usage

1. Open `http://localhost:8000`
2. Upload your client Excel file (`.xlsx`, `.ods`, or `.xls`)
3. The app auto-detects the LEI column
4. Click **Check LEIs** — watch the live feed
5. Download the enriched file with Entity Status + Next Renewal Date written back

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload Excel; returns `job_id` + preview |
| POST | `/api/process/{job_id}` | Start async batch check |
| GET | `/api/stream/{job_id}` | SSE real-time progress stream |
| GET | `/api/status/{job_id}` | Poll-based status + results |
| GET | `/api/download/{job_id}` | Download enriched Excel |
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |

---

## 🛡️ Security & Quality

| Check | Tool | Status |
|-------|------|--------|
| Unit + integration tests | pytest + anyio | ✅ 42 tests |
| Dependency vulnerabilities (SCA) | pip-audit | ✅ CI enforced |
| Static code analysis | bandit | ✅ MEDIUM+ severity |
| Secret scanning | TruffleHog | ✅ verified secrets only |
| SBOM generation | Syft | ✅ CycloneDX + SPDX |
| Container build | Docker Buildx | ✅ on every push to main |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12, FastAPI (async) |
| Frontend | Vanilla HTML/CSS/JS (no build step) |
| Excel I/O | openpyxl |
| HTTP client | httpx (async, connection pooling) |
| HTML parsing | BeautifulSoup4 + lxml |
| Rate limiting | Custom token-bucket (per host) |
| Progress streaming | Server-Sent Events |
| Observability | prometheus-client, structured JSON logs |
| Containerisation | Docker + Docker Compose |
| CI/CD | GitHub Actions |

---

## ⚙️ Anti-blocking Strategy

Banks typically have hundreds of LEI codes. The app handles this with:

- **Token bucket** per host: GLEIF → 2 req/s, lei-lookup → 0.4 req/s
- **Exponential back-off** on HTTP 429 / 503
- **Shared connection pool** (single `httpx.AsyncClient` for the full batch)
- **Browser-like headers** on scraping requests

---

## 📄 License

GPL-3.0 — see [LICENSE](LICENSE)

---

<<<<<<< HEAD
Built by [Thanasis Koufos](https://www.thanasis-codes.eu) · [GitHub](https://github.com/ThanasisSoftwareDeveloper)
=======
Built by [Thanasis Koufos](https://www.thanasis-codes.eu) · [GitHub](https://github.com/ThanasisSoftwareDeveloper)
>>>>>>> d647e15 (docs: update README)
