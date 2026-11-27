from decimal import Decimal
from pathlib import Path

from pyths._sector_codec import decode_sector_response


def test_synthetic_stock_projection():
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures/synthetic/sector-stock.json"
    )
    page = decode_sector_response(fixture.read_bytes(), kind="stock")
    assert page.total == 16 and len(page.rows) == 16
    assert page.rows[0].code == "900101"
    assert page.rows[0].main_net_inflow == Decimal("123456.50")
    assert {row.market for row in page.rows} == {"17", "33", "151"}
    assert sum(row.main_net_inflow is None for row in page.rows) == 3
