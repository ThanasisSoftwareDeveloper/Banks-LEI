"""Shared pytest fixtures for FindLEI test suite."""

import io
import pytest
import openpyxl


@pytest.fixture()
def sample_workbook_bytes() -> bytes:
    """
    Returns bytes of an .xlsx workbook with a LEI column.
    Uses real-format (but fictitious) 20-char LEI strings.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Company Name", "LEI", "Country"])
    ws.append(["Alpha Bank SA",    "AAAAAA1234567890AA01", "GR"])
    ws.append(["Beta Finance Ltd", "BBBBBB1234567890BB02", "DE"])
    ws.append(["Gamma Capital",    "CCCCCC1234567890CC03", "FR"])
    ws.append(["Delta Holdings",   "DDDDDD1234567890DD04", "GB"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def sample_workbook_no_header_bytes() -> bytes:
    """Workbook where LEI codes appear without a 'LEI' header label."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["AAAAAA1234567890AA01", "Alpha Bank SA"])
    ws.append(["BBBBBB1234567890BB02", "Beta Finance Ltd"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
