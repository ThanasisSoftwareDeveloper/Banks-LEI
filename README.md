# FindLEI — LEI Batch Compliance Checker

> **findlei.com** · Checks Entity Status & Next Renewal Date for every LEI in your Excel file.

---

## What it does

1. Upload an `.xlsx`, `.ods`, or `.xls` client spreadsheet.
2. The app auto-detects the LEI column (by header name or 20-char pattern).
3. For every LEI it queries:
   - **GLEIF official API** first (`api.gleif.org`) — free, no key required.
   - **lei-lookup.com** as fallback if either field is missing.
4. Results are written back as two new columns (`Entity Status`, `Next Renewal Date`) with colour-coding and a third `Source` column.
5. Download the enriched file with one click.

### Anti-blocking strategy
- **Token bucket** rate limiter per host (GLEIF: 2 req/s, lei-lookup: 0.4 req/s).
- **Exponential back-off** on HTTP 429 / 503.
- Shared persistent HTTP connection pool (`httpx.AsyncClient` + keep-alive).
- Rotating `User-Agent` consistent with a real browser.

---

## Stack

| Layer    | Technology                              |
|----------|-----------------------------------------|
| Backend  | Python 3.12 + **FastAPI** (async)       |
| Frontend | Vanilla HTML/CSS/JS (no build step)     |
| Excel    | **openpyxl** (write) + pandas fallback  |
| HTTP     | **httpx** async                         |
| Scraping | **BeautifulSoup4** + lxml               |
| Progress | Server-Sent Events                      |

---

## Local development

```bash
# 1. Clone / download the project
cd findlei

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run dev server
uvicorn main:app --reload --port 8000

# 5. Open http://localhost:8000
```

---

## Docker deployment (recommended for findlei.com)

```bash
# Build & start
docker compose up -d --build

# View logs
docker compose logs -f

# Stop
docker compose down
```

The app will be available on port **8000**.

---

## Nginx reverse proxy (production)

Put this in `/etc/nginx/sites-available/findlei`:

```nginx
server {
    listen 80;
    server_name findlei.com www.findlei.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name findlei.com www.findlei.com;

    ssl_certificate     /etc/letsencrypt/live/findlei.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/findlei.com/privkey.pem;

    # Important for SSE (disable proxy buffering)
    proxy_buffering off;
    proxy_cache off;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 300s;   # long timeout for batch jobs
    }
}
```

Then:
```bash
sudo certbot --nginx -d findlei.com -d www.findlei.com
sudo nginx -t && sudo systemctl reload nginx
```

---

## Production notes

- **Multi-worker**: With `--workers 2` (Dockerfile default), jobs are stored in-process memory.  
  For more than 2 workers, replace the `jobs` dict in `main.py` with Redis.
- **File size**: Uploads capped at 50 MB. Adjust in `main.py` if needed.
- **GLEIF API**: No authentication required. Rate limit is generous (~10 req/s per IP in practice; the app stays well under that).
- **lei-lookup.com**: If the site changes its HTML structure, update `_parse_lei_lookup_html()` in `lei_checker.py`.

---

## Project structure

```
findlei/
├── main.py             FastAPI app + routes
├── lei_checker.py      GLEIF API + lei-lookup scraper + batch processor
├── excel_handler.py    Excel read/write (openpyxl)
├── rate_limiter.py     Token bucket per host
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── static/
    └── index.html      Full frontend (single file, no build step)
```
