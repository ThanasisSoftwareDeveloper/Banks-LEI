"""
Tests for the LEI checker engine.
All external HTTP calls are mocked — no real network access.
"""

import json
import pytest
import httpx
import respx

from lei_checker import (
    _check_gleif,
    _check_lei_lookup,
    _fmt_date,
    _parse_lei_lookup_html,
    check_lei_batch,
    GLEIF_API,
    LEI_LOOKUP_WEB,
)

GLEIF_RESPONSE = {
    "data": {
        "attributes": {
            "entity":       {"status": "ACTIVE"},
            "registration": {"nextRenewalDate": "2025-06-30T00:00:00Z"},
        }
    }
}

VALID_LEI = "7LTWFZYICNSX8D621K86"


# ── Date formatting ───────────────────────────────────────────────────────────
class TestFmtDate:
    def test_iso_with_z(self):
        assert _fmt_date("2025-03-31T00:00:00Z") == "2025-03-31"

    def test_iso_with_offset(self):
        assert _fmt_date("2025-06-30T12:00:00+02:00") == "2025-06-30"

    def test_plain_date(self):
        assert _fmt_date("2025-12-31") == "2025-12-31"

    def test_empty_string(self):
        assert _fmt_date("") == ""

    def test_none_coercion(self):
        assert _fmt_date("") == ""


# ── HTML parser ───────────────────────────────────────────────────────────────
class TestParseLeiLookupHtml:
    _TABLE_HTML = """
    <table>
      <tr><th>Entity Status</th><td>ACTIVE</td></tr>
      <tr><th>Next Renewal Date</th><td>2025-09-30</td></tr>
    </table>
    """

    _DL_HTML = """
    <dl>
      <dt>entity status</dt><dd>ACTIVE</dd>
      <dt>next renewal</dt><dd>2026-01-01</dd>
    </dl>
    """

    def test_parses_table(self):
        status, renewal = _parse_lei_lookup_html(self._TABLE_HTML)
        assert status  == "ACTIVE"
        assert renewal == "2025-09-30"

    def test_parses_dl(self):
        status, renewal = _parse_lei_lookup_html(self._DL_HTML)
        assert status  == "ACTIVE"
        assert renewal == "2026-01-01"

    def test_empty_html(self):
        status, renewal = _parse_lei_lookup_html("")
        assert status  == ""
        assert renewal == ""


# ── GLEIF API (mocked) ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_check_gleif_success():
    url = GLEIF_API.format(lei=VALID_LEI)
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, json=GLEIF_RESPONSE))
        async with httpx.AsyncClient() as client:
            status, renewal = await _check_gleif(client, VALID_LEI)
    assert status  == "ACTIVE"
    assert renewal == "2025-06-30"


@pytest.mark.asyncio
async def test_check_gleif_404_returns_empty():
    url = GLEIF_API.format(lei=VALID_LEI)
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as client:
            status, renewal = await _check_gleif(client, VALID_LEI)
    assert status  == ""
    assert renewal == ""


@pytest.mark.asyncio
async def test_check_gleif_malformed_json():
    url = GLEIF_API.format(lei=VALID_LEI)
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, text="not json"))
        async with httpx.AsyncClient() as client:
            status, renewal = await _check_gleif(client, VALID_LEI)
    assert status  == ""
    assert renewal == ""


# ── Batch processor ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_batch_skips_blank_leis():
    with respx.mock:
        respx.get(url__regex=r".*gleif.*").mock(return_value=httpx.Response(404))
        respx.get(url__regex=r".*lei-lookup.*").mock(return_value=httpx.Response(404))
        results = await check_lei_batch(["", "  ", ""])
    assert results == []


@pytest.mark.asyncio
async def test_batch_marks_invalid_format():
    results = await check_lei_batch(["NOT-A-LEI", "123", "toolongstringthatisnotlei99"])
    statuses = [r["entity_status"] for r in results]
    assert all(s == "INVALID FORMAT" for s in statuses)


@pytest.mark.asyncio
async def test_batch_calls_fallback_when_gleif_incomplete():
    gleif_partial = {
        "data": {
            "attributes": {
                "entity":       {"status": "ACTIVE"},
                "registration": {"nextRenewalDate": ""},
            }
        }
    }
    fallback_html = """
    <table>
      <tr><th>Entity Status</th><td>ACTIVE</td></tr>
      <tr><th>Next Renewal Date</th><td>2025-09-30</td></tr>
    </table>
    """
    with respx.mock:
        respx.get(GLEIF_API.format(lei=VALID_LEI)).mock(
            return_value=httpx.Response(200, json=gleif_partial)
        )
        respx.get(url__regex=r".*lei-lookup.*").mock(
            return_value=httpx.Response(200, text=fallback_html)
        )
        results = await check_lei_batch([VALID_LEI])

    assert len(results) == 1
    assert results[0]["entity_status"] == "ACTIVE"
    assert results[0]["next_renewal"]  == "2025-09-30"


@pytest.mark.asyncio
async def test_batch_on_progress_called_for_each_lei():
    leis = [VALID_LEI, "AAAAAA1234567890AA01", "BBBBBB1234567890BB02"]
    calls = []
    with respx.mock:
        respx.get(url__regex=r".*gleif.*").mock(return_value=httpx.Response(404))
        respx.get(url__regex=r".*lei-lookup.*").mock(return_value=httpx.Response(404))
        await check_lei_batch(leis, on_progress=lambda idx, r: calls.append(idx))
    assert len(calls) == 3
    assert calls == [0, 1, 2]