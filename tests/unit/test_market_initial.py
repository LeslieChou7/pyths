"""M8新会话首帧的合成回归；frame0仍须通过业务身份校验。"""

import struct

import pytest

from pyths._market_fund import decode_fund_response
from pyths._market_size import decode_size_response
from pyths._market_turnover import decode_turnover_response
from pyths.errors import ThsProtocolError
from tests.unit.test_market_fund import curve as fund_curve
from tests.unit.test_market_size import snappy, table
from tests.unit.test_market_turnover import curve as turnover_curve

CASES = (
    (decode_size_response, table, 0x1100, {}),
    (decode_fund_response, fund_curve, 0x1120, {"kind": "sh"}),
    (decode_turnover_response, turnover_curve, 0x1100, {}),
)


def initial(
    body, flags, *, package=1, instance=1, frame=0, marker=b"\x00\xff", compressed=True
):
    payload = snappy(body) if compressed else body
    return struct.pack(
        "<HiiHiii", 26, package, flags, instance, len(payload), frame, 0
    ) + marker, payload


@pytest.mark.parametrize("decoder,factory,flags,kwargs", CASES)
def test_initial_frame_is_accepted_only_with_full_business_validation(
    decoder, factory, flags, kwargs
):
    head, payload = initial(factory(), flags)
    assert decoder(head, payload, package_id=1, instance_id=1, **kwargs) is not None


@pytest.mark.parametrize("decoder,factory,flags,kwargs", CASES)
@pytest.mark.parametrize(
    "changes", [{"package": 2}, {"instance": 2}, {"frame": 17}, {"marker": b"\x03\xff"}]
)
def test_initial_does_not_relax_other_identifiers(
    decoder, factory, flags, kwargs, changes
):
    head, payload = initial(factory(), flags, **changes)
    with pytest.raises(ThsProtocolError):
        decoder(head, payload, package_id=1, instance_id=1, **kwargs)


@pytest.mark.parametrize(
    "decoder,body,flags,kwargs",
    (
        (decode_size_response, table(codes=("1B0852", "1B0300")), 0x1100, {}),
        (decode_fund_response, fund_curve(code="399001"), 0x1120, {"kind": "sh"}),
        (decode_turnover_response, turnover_curve(code="000001"), 0x1100, {}),
    ),
)
def test_frame_zero_wrong_security_still_fails(decoder, body, flags, kwargs):
    head, payload = initial(body, flags)
    with pytest.raises(ThsProtocolError):
        decoder(head, payload, package_id=1, instance_id=1, **kwargs)


@pytest.mark.parametrize(
    "decoder,factory,flags,kwargs",
    (
        (decode_fund_response, fund_curve, 0x120, {"kind": "sh"}),
        (decode_turnover_response, turnover_curve, 0x100, {}),
    ),
)
@pytest.mark.parametrize(
    "changes", ({}, {"package": 2}, {"instance": 2}, {"frame": 17})
)
def test_intraday_uncompressed_initial_retains_correlation(
    decoder, factory, flags, kwargs, changes
):
    head, payload = initial(factory(), flags, compressed=False, **changes)
    if changes:
        with pytest.raises(ThsProtocolError):
            decoder(head, payload, package_id=1, instance_id=1, **kwargs)
    else:
        assert decoder(head, payload, package_id=1, instance_id=1, **kwargs) is not None


@pytest.mark.parametrize(
    "decoder,body,flags,kwargs",
    (
        (decode_fund_response, fund_curve(code="399001"), 0x120, {"kind": "sh"}),
        (decode_turnover_response, turnover_curve(code="000001"), 0x100, {}),
    ),
)
def test_intraday_uncompressed_initial_still_checks_source(
    decoder, body, flags, kwargs
):
    head, payload = initial(body, flags, compressed=False)
    with pytest.raises(ThsProtocolError):
        decoder(head, payload, package_id=1, instance_id=1, **kwargs)
