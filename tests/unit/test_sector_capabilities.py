from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from pyths import SectorCapabilities, ThsClientClosedError, ths


def test_local_capability_does_not_probe_or_claim_network_support():
    with patch("socket.socket", side_effect=AssertionError("unexpected network")):
        with ths() as client:
            result = client.get_sector_capabilities()
            assert isinstance(result, SectorCapabilities)
            assert result.sdk_network_verified is False
            assert result.independent_http_probe_verified is True
            assert result.independent_http_probe_scope
            assert result.status == "sdk_partially_verified"
            assert len(result.verified_business_scopes) == 30
            assert result.verified_platforms == ("windows", "linux")
            assert result.limitations
            with pytest.raises(FrozenInstanceError):
                result.sdk_network_verified = True
        with pytest.raises(ThsClientClosedError):
            client.get_sector_capabilities()
