import pytest

from pyths._codec import StringTable, TableHeader
from pyths._quote import quote_from_table
from pyths.errors import ThsProtocolError


def table(cells):
    return StringTable("", tuple(cells), TableHeader(0, 0, 0, 24, 0, ()), (), ())


def test_display_mapping_preserves_identity_and_missing():
    quote = quote_from_table(
        table(
            [
                (4, "000001", 0),
                (36103, "33", 0),
                (19, "1.23", 48),
                (13, "186.42", 64),
                (34315, "0.87", 32),
            ]
        ),
        stock_code="000001",
        market="33",
    )
    assert quote.stock_code == "000001"
    assert quote.latest is None
    assert quote.turnover.raw == "1.23"
    assert quote.turnover.display == "1.23亿"
    assert quote.turnover.unit is None
    assert quote.volume.unit == "手"
    assert quote.change_rate.unit == "%"
    assert quote.received_at is None


@pytest.mark.parametrize("cells", [[], [(4, "000002", 0), (36103, "33", 0)]])
def test_missing_or_wrong_identity(cells):
    with pytest.raises(ThsProtocolError, match="identity"):
        quote_from_table(table(cells), stock_code="000001", market="33")
