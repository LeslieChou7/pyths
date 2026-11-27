"""已观察M10a字段的合成离线闭环；不证明窗口或网络兼容。"""

import struct
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pyths import ths
from pyths._advanced_ranking import (
    advanced_page,
    decode_advanced_response,
    encode_advanced_body,
)
from pyths._tb3 import Cell
from pyths.errors import ThsProtocolError
from tests.ranking_fixture import reply, table

NOW = datetime(2026, 11, 6, tzinfo=UTC)


def row():
    return {
        4: Cell("000001", 15, 0),
        36103: Cell("33", 15, 0),
        55: Cell("Synthetic", 15, 0),
        48: Cell(Decimal("-1.20"), 42, 0),
        34370: Cell(Decimal("0.00"), 10, 0),
        34391: Cell(Decimal("2.34"), 58, 0),
    }


@pytest.mark.parametrize(
    "sort,field",
    [
        ("rapid_change_rate", 48),
        ("large_order_net_volume", 34370),
        ("main_net_inflow", 34391),
    ],
)
def test_wire_body_and_public_gate(sort, field):
    body = encode_advanced_body(sort=sort, instance_id=7, active_instances=(2, 7))
    assert (
        body
        == (
            "[frame]\r\nid=2312\r\npageList=2,7\r\nreqPage=7\r\nreqPageCount=1\r\n[7]\r\n"
            "id=1282\r\nstartrow=0\r\nrowcount=24\r\nmarketId=0\r\nsortorder=0\r\n"
            f"sortid={field}\r\n"
        ).encode()
    )
    with ths() as client, pytest.raises(ValueError, match="explicit endpoint"):
        client.get_stock_ranking(sort=sort)


def test_metric_display_and_unknown_semantics():
    page = advanced_page(
        (row(),),
        {34055: 0, 34056: 1},
        sort="rapid_change_rate",
        start=0,
        received_at=NOW,
    )
    item = page.items[0]
    assert item.stock_code == "000001"
    assert item.rapid_change_rate.display == "-1.20%"
    assert item.large_order_net_volume.display == "0.00"
    assert item.large_order_net_volume.display_unit is None
    assert item.main_net_inflow.display == "2.34亿"
    assert page.window is None and page.unknowns and page.has_more is False


def test_missing_value_not_zero_and_unknown_column_ignored():
    data = row()
    data[48] = Cell(None, 42, 0)
    data[65000] = Cell("ignored", 15, 0)
    page = advanced_page(
        (data,), {34055: 0}, sort="rapid_change_rate", start=0, received_at=NOW
    )
    assert page.items[0].rapid_change_rate is None
    assert page.total is None and page.has_more is None


@pytest.mark.parametrize("change", ["identity", "sort", "metric", "format", "page"])
def test_malformed_candidate_rejected(change):
    data, fields = row(), {34055: 0, 34056: 1}
    if change == "identity":
        data[4] = Cell("1", 15, 0)
    elif change == "sort":
        del data[48]
    elif change == "metric":
        data[48] = Cell(Decimal("NaN"), 42, 0)
    elif change == "format":
        data[48] = Cell(Decimal(1), 255, 0)
    else:
        fields[34055] = 1
    with pytest.raises(ThsProtocolError):
        advanced_page(
            (data,), fields, sort="rapid_change_rate", start=0, received_at=NOW
        )


@pytest.mark.parametrize("initial", [False, True])
def test_full_synthetic_wire_path_checks_correlation(initial):
    original = struct.pack("<HBB", 4096 | 34818, 4, 0)
    payload = table(0)
    assert payload.count(original) == 1
    payload = payload.replace(original, struct.pack("<HBB", 4096 | 48, 4, 0))
    wire = reply(0x1130, payload, frame=0 if initial else 2312, package=7, instance=8)
    page = decode_advanced_response(
        wire[:26],
        wire[26:],
        sort="rapid_change_rate",
        package_id=7,
        instance_id=8,
        start=0,
        received_at=NOW,
        allow_initial_frame_zero=initial,
    )
    assert page.items[0].rapid_change_rate.display == "0.01%"
    with pytest.raises(ThsProtocolError):
        decode_advanced_response(
            wire[:26],
            wire[26:],
            sort="rapid_change_rate",
            package_id=7,
            instance_id=9,
            start=0,
            received_at=NOW,
            allow_initial_frame_zero=initial,
        )
    if initial:
        with pytest.raises(ThsProtocolError):
            decode_advanced_response(
                wire[:26],
                wire[26:],
                sort="rapid_change_rate",
                package_id=7,
                instance_id=8,
                start=0,
                received_at=NOW,
            )
