"""公共失败分类；不附原始报文或凭据。"""


class ThsError(Exception):
    """ThsError 失败类型。"""


class ThsNetworkError(ThsError):
    """ThsNetworkError 失败类型。"""


class ThsProtocolError(ThsError):
    """ThsProtocolError 失败类型。"""


class ThsAuthenticationError(ThsError):
    """ThsAuthenticationError 失败类型。"""


class ThsRateLimitError(ThsError):
    """ThsRateLimitError 失败类型。"""


class ThsBusinessError(ThsError):
    """ThsBusinessError 失败类型。"""


class ThsClientClosedError(ThsError):
    """ThsClientClosedError 失败类型。"""
