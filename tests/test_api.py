"""
Integration tests for the FastAPI endpoints.
Uses httpx.AsyncClient with ASGI transport — no real server needed.
"""

import io
import asyncio
import pytest
import openpyxl
from httpx import AsyncClient, ASGITransport

from main import app


def _make_xlsx_bytes(leis=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Company", "LEI"])
    for lei in (leis or ["AAAAAA1234567890AA01", "BBBBBB1234567890BB02"]):
        ws.append(["Test Co", lei])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_health_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_metrics_endpoint_returns_prometheus_format():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/metrics")
    assert resp.status_code == 200
    assert "findlei_" in resp.text


@pytest.mark.anyio
async def test_upload_valid_xlsx():
    xlsx = _make_xlsx_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/upload",
            files={"file": ("clients.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["lei_count"] == 2


@pytest.mark.anyio
async def test_upload_rejects_csv():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/upload",
            files={"file": ("data.csv", b"lei,company\nABC,XYZ", "text/csv")},
        )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_upload_rejects_too_large_file():
    big = b"x" * (51 * 1024 * 1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/upload",
            files={"file": ("big.xlsx", big, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert resp.status_code == 413


@pytest.mark.anyio
async def test_status_unknown_job_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/status/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_process_unknown_job_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/process/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_download_before_completion_returns_409():
    xlsx = _make_xlsx_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        up = await ac.post(
            "/api/upload",
            files={"file": ("c.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        job_id = up.json()["job_id"]
        resp = await ac.get(f"/api/download/{job_id}")
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_full_upload_process_status_flow(monkeypatch):
    """
    Simulate a complete job lifecycle without real network calls.
    Monkeypatches check_lei_batch to return instant mock results.
    """
    import main as main_module

    async def mock_batch(leis, on_progress=None):
        results = []
        for idx, lei in enumerate(leis):
            r = {"lei": lei, "entity_status": "ACTIVE", "next_renewal": "2025-12-31", "source": "GLEIF"}
            results.append(r)
            if on_progress:
                on_progress(idx, r)
        return results

    monkeypatch.setattr(main_module, "check_lei_batch", mock_batch)

    xlsx = _make_xlsx_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Upload
        up = await ac.post(
            "/api/upload",
            files={"file": ("c.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert up.status_code == 200
        job_id = up.json()["job_id"]

        # Start processing
        proc = await ac.post(f"/api/process/{job_id}")
        assert proc.status_code == 200

        # Wait for background task
        await asyncio.sleep(0.5)

        # Check status
        status = await ac.get(f"/api/status/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert len(body["results"]) == 2
        assert body["results"][0]["entity_status"] == "ACTIVE"
