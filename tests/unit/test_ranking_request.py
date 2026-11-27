import pytest

from pyths._ranking_request import encode_ranking_request
from pyths._transform import decode_body


def test_wire_has_independent_identifiers_and_encoded_body():
    packet = encode_ranking_request(
        package_id=7,
        instance_id=8,
        start=24,
        sort="change_rate",
        direction="asc",
        app_info="synthetic",
        session_id="local-only",
        state_word=123,
        trace_id="synthetic-trace",
    )
    length = int.from_bytes(packet[:2], "little")
    assert int.from_bytes(packet[2:6], "little") == 7
    assert int.from_bytes(packet[16:20], "little") == 2312
    assert int.from_bytes(packet[24:28], "little") == 123
    assert b"pageList=8\r\nreqPage=8\r\n" in decode_body(packet[length:])
    assert b"startrow=24\r\n" in decode_body(packet[length:])


from pyths._ranking_request import encode_ranking_body
from pyths.errors import ThsProtocolError


def test_observed_request_text():
    expected = (
        b"[frame]\r\nid=2312\r\npageList=10803,10802,10804,10807\r\n"
        b"reqPage=10807\r\nreqPageCount=1\r\n[10807]\r\nid=1282\r\n"
        b"startrow=0\r\nrowcount=24\r\nmarketId=0\r\n"
        b"sortorder=0\r\nsortid=34818\r\n"
    )
    assert (
        encode_ranking_body(
            instance_id=10807,
            start=0,
            sort="change_rate",
            direction="desc",
            active_instances=(10803, 10802, 10804, 10807),
        )
        == expected
    )


@pytest.mark.parametrize(
    "sort,direction,key,order",
    [
        ("change_rate", "desc", 34818, 0),
        ("change_rate", "asc", 34818, 1),
        ("turnover", "desc", 19, 0),
        ("rapid_change_rate", "desc", 48, 0),
        ("large_order_net_volume", "desc", 34370, 0),
        ("main_net_inflow", "desc", 34391, 0),
    ],
)
def test_supported_combinations(sort, direction, key, order):
    body = encode_ranking_body(instance_id=1, start=281, sort=sort, direction=direction)
    assert f"sortorder={order}\r\nsortid={key}\r\n".encode() in body
    assert b"startrow=281\r\n" in body


@pytest.mark.parametrize("start", [-1, True, 10000000, "24"])
def test_invalid_offset(start):
    with pytest.raises(ValueError):
        encode_ranking_body(
            instance_id=1, start=start, sort="turnover", direction="desc"
        )


def test_reject_unsupported_and_bad_instances():
    with pytest.raises(ValueError):
        encode_ranking_body(instance_id=1, start=0, sort="turnover", direction="asc")
    for ids in [(), (2,), (1, 1), (True,)]:
        with pytest.raises(ThsProtocolError):
            encode_ranking_body(
                instance_id=1,
                start=0,
                sort="turnover",
                direction="desc",
                active_instances=ids,
            )
