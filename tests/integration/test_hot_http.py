import pytest

from pyths import (
    ThsAuthenticationError,
    ThsBusinessError,
    ThsProtocolError,
    ThsRateLimitError,
    _hot,
    ths,
)
from pyths._http import request
from tests.hot_fixture import payload
from tests.integration.test_http import server


@pytest.mark.parametrize("board", ["stock_hour", "stock_24h"])
def test_public_hot_api_over_local_http(monkeypatch, board):
    with server(body=payload(), headers=(("Content-Encoding", "identity"),)) as (
        url,
        seen,
    ):

        def local_request(target, **kwargs):
            assert target == "https://eq.10jqka.com.cn" + _hot.PATHS[board]
            return request(url + _hot.PATHS[board], **kwargs)

        monkeypatch.setattr(_hot, "request", local_request)
        with ths() as client:
            result = client.get_hot_ranking(board=board)
        assert result.items[0].stock_code == "000001"
        assert seen == [("GET", _hot.PATHS[board], None)]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, b"secret", ThsAuthenticationError),
        (403, b"secret", ThsAuthenticationError),
        (429, b"secret", ThsRateLimitError),
        (500, b"secret", ThsBusinessError),
        (302, b"", ThsProtocolError),
        (200, b"<html>not a list</html>", ThsProtocolError),
    ],
)
def test_public_hot_http_failures_do_not_retry(monkeypatch, status, body, error):
    with server(status=status, body=body) as (url, seen):
        monkeypatch.setattr(_hot, "request", lambda target, **kw: request(url, **kw))
        with ths(retries=1) as client, pytest.raises(error) as caught:
            client.get_hot_ranking(board="stock_hour")
        assert len(seen) == 1
        assert "secret" not in str(caught.value)
