"""独立显式联网验收；默认pytest不收集本目录。"""

import os

import pytest

from pyths import ths


@pytest.mark.parametrize(
    "code", os.environ.get("PYTHS_LIVE_CODES", "000001").split(",")
)
def test_authorized_single_quote(code):
    if os.environ.get("PYTHS_LIVE") != "1":
        pytest.skip("explicit PYTHS_LIVE=1 required")
    keys = ("PYTHS_LIVE_HOST", "PYTHS_LIVE_PORT", "PYTHS_APP_CONFIG", "PYTHS_APP_INFO")
    if any(not os.environ.get(key) for key in keys):
        pytest.skip("explicit authorized endpoint and App config required")
    with ths(
        endpoint=(os.environ[keys[0]], int(os.environ[keys[1]])),
        app_config=os.environ[keys[2]],
        app_info=os.environ[keys[3]],
    ) as client:
        quote = client.get_quote(code, market="33")
        assert (quote.stock_code, quote.market) == (code, "33")
        for name in (
            "latest",
            "change",
            "change_rate",
            "open",
            "high",
            "low",
            "previous_close",
            "volume",
            "turnover",
        ):
            value = getattr(quote, name)
            assert value is not None and value.display
    assert client.closed
