"""
LEI lookup engine.

Strategy:
  1. Try GLEIF official REST API  →  https://api.gleif.org/api/v1/lei-records/{lei}
  2. If entity_status OR next_renewal still missing → fallback to lei-lookup.com scrape

Rate limiting is handled by rate_limiter.py (token buckets per host).
Exponential back-off on HTTP 429 / 503 / connection errors.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from rate_limiter import rate_limiter

logger = logging.getLogger("findlei.checker")

# ── Constants ────────────────────────────────────────────────────────────────
GLEIF_API = "https://api.gleif.org/api/v1/lei-records/{lei}"
LEI_LOOKUP_API = "https://api.lei-lookup.com/api/v1"  # primary
LEI_LOOKUP_WEB = "https://www.lei-lookup.com/single/"  # fallback scrape

MAX_RETRIES = 4
BACKOFF_BASE = 1.5          # seconds; multiplied by attempt^2
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

LEI_RE = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")


# ── Helpers ──────────────────────────────────────────────────────────────────
def _fmt_date(iso: str) -> str:
    """Normalize an ISO-8601 date string to YYYY-MM-DD."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # Return whatever was there
        return iso[:10] if len(iso) >= 10 else iso


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    host_key: str,
    headers: Optional[Dict] = None,
    params: Optional[Dict] = None,
) -> Optional[httpx.Response]:
    """GET with token-bucket rate limiting + exponential back-off."""
    hdrs = {**BASE_HEADERS, **(headers or {})}

    for attempt in range(MAX_RETRIES):
        await rate_limiter.wait(host_key)
        try:
            resp = await client.get(url, headers=hdrs, params=params)

            if resp.status_code in (429, 503):
                retry_after = float(resp.headers.get("Retry-After", BACKOFF_BASE ** (attempt + 2)))
                logger.warning(
                    "[%s] HTTP %d – waiting %.1fs (attempt %d/%d)",
                    host_key, resp.status_code, retry_after, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(retry_after)
                continue

            return resp

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            wait = BACKOFF_BASE ** (attempt + 1)
            logger.warning("[%s] %s – retrying in %.1fs", host_key, exc, wait)
            await asyncio.sleep(wait)

    logger.error("[%s] All %d attempts failed for %s", host_key, MAX_RETRIES, url)
    return None


# ── Source 1: GLEIF official API ─────────────────────────────────────────────
async def _check_gleif(client: httpx.AsyncClient, lei: str) -> Tuple[str, str]:
    """
    Returns (entity_status, next_renewal_date).
    Both strings; empty string means not found.
    """
    url = GLEIF_API.format(lei=lei)
    resp = await _get_with_retry(
        client, url, "gleif", headers={"Accept": "application/vnd.api+json"}
    )

    if resp is None or resp.status_code != 200:
        return "", ""

    try:
        body = resp.json()
        attrs = body.get("data", {}).get("attributes", {})
        entity_status = attrs.get("entity", {}).get("status", "")
        next_renewal = _fmt_date(
            attrs.get("registration", {}).get("nextRenewalDate", "")
        )
        return entity_status, next_renewal
    except Exception as exc:
        logger.warning("[gleif] JSON parse error for %s: %s", lei, exc)
        return "", ""


# ── Source 2: lei-lookup.com  ────────────────────────────────────────────────
async def _check_lei_lookup(client: httpx.AsyncClient, lei: str) -> Tuple[str, str]:
    """
    Try the lei-lookup JSON endpoint first, fall back to HTML scraping.
    Returns (entity_status, next_renewal_date).
    """
    # -- Attempt A: JSON endpoint (undocumented but stable)
    url_json = f"{LEI_LOOKUP_API}/{lei}"
    resp = await _get_with_retry(
        client, url_json, "lei-lookup",
        headers={"Accept": "application/json"}
    )
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            # Possible keys vary; try common shapes
            status = (
                data.get("entityStatus")
                or data.get("entity_status")
                or data.get("Entity", {}).get("Status", "")
                or data.get("status", "")
            )
            renewal = _fmt_date(
                data.get("nextRenewalDate")
                or data.get("next_renewal_date")
                or data.get("Registration", {}).get("NextRenewalDate", "")
                or ""
            )
            if status or renewal:
                return str(status), renewal
        except Exception:
            pass

    # -- Attempt B: HTML scraping
    url_html = f"{LEI_LOOKUP_WEB}?lei={lei}"
    resp = await _get_with_retry(
        client, url_html, "lei-lookup",
        headers={"Accept": "text/html,application/xhtml+xml"}
    )
    if resp and resp.status_code == 200:
        return _parse_lei_lookup_html(resp.text)

    return "", ""


def _parse_lei_lookup_html(html: str) -> Tuple[str, str]:
    """Extract Entity Status and Next Renewal from lei-lookup HTML page."""
    soup = BeautifulSoup(html, "lxml")
    status = ""
    renewal = ""

    # Walk all table rows and definition-list items looking for the fields
    label_map = {
        "entity status":    "status",
        "registration status": "status",
        "next renewal":     "renewal",
        "next renewal date": "renewal",
        "renewal date":     "renewal",
    }

    # <table> pattern
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).lower()
            value = cells[-1].get_text(strip=True)
            if label_map.get(label) == "status":
                status = value
            elif label_map.get(label) == "renewal":
                renewal = _fmt_date(value)

    # <dl> / <dt>/<dd> pattern
    for dt in soup.find_all("dt"):
        label = dt.get_text(strip=True).lower()
        dd = dt.find_next_sibling("dd")
        if dd:
            value = dd.get_text(strip=True)
            if label_map.get(label) == "status":
                status = value
            elif label_map.get(label) == "renewal":
                renewal = _fmt_date(value)

    # Generic text search as last resort
    if not status or not renewal:
        text = soup.get_text(separator="\n")
        for line in text.splitlines():
            lo = line.strip().lower()
            if not status and ("entity status" in lo or "registration status" in lo):
                # next non-empty line is probably the value
                pass  # done via table parse; skip noisy fallback
            if not renewal and ("next renewal" in lo):
                pass

    return status, renewal


# ── Batch processor ───────────────────────────────────────────────────────────
async def check_lei_batch(
    leis: List[str],
    on_progress: Optional[Callable[[int, Dict], None]] = None,
) -> List[Dict]:
    """
    Process a list of LEI codes.

    For each LEI:
      • Try GLEIF API.
      • If either field is empty, try lei-lookup.com.
      • Merge: prefer GLEIF values when available.

    Calls on_progress(index, result_dict) after each LEI is resolved.
    """
    results: List[Dict] = []

    # Single shared client for connection pooling
    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    ) as client:
        for idx, raw_lei in enumerate(leis):
            lei = raw_lei.strip().upper()

            # Skip blank rows
            if not lei:
                continue

            # Validate format (20-char alphanumeric)
            if not LEI_RE.match(lei):
                result = {
                    "lei": raw_lei,
                    "entity_status": "INVALID FORMAT",
                    "next_renewal": "",
                    "source": "—",
                }
                results.append(result)
                if on_progress:
                    on_progress(idx, result)
                continue

            # --- Step 1: GLEIF ---
            g_status, g_renewal = await _check_gleif(client, lei)

            entity_status = g_status
            next_renewal = g_renewal
            source = "GLEIF" if (g_status or g_renewal) else ""

            # --- Step 2: Fallback if either field is missing ---
            if not entity_status or not next_renewal:
                l_status, l_renewal = await _check_lei_lookup(client, lei)

                if not entity_status and l_status:
                    entity_status = l_status
                    source = "lei-lookup" if not source else "GLEIF + lei-lookup"
                if not next_renewal and l_renewal:
                    next_renewal = l_renewal
                    source = "lei-lookup" if not source else "GLEIF + lei-lookup"

            # --- Build result ---
            if not entity_status and not next_renewal:
                result = {
                    "lei": raw_lei,
                    "entity_status": "NOT FOUND",
                    "next_renewal": "",
                    "source": "—",
                }
            else:
                result = {
                    "lei": raw_lei,
                    "entity_status": entity_status or "",
                    "next_renewal": next_renewal or "",
                    "source": source,
                }

            results.append(result)
            logger.info(
                "[%d/%d] %s → status=%r renewal=%r source=%s",
                idx + 1, len(leis), lei,
                result["entity_status"], result["next_renewal"], result["source"],
            )

            if on_progress:
                on_progress(idx, result)

    return results
