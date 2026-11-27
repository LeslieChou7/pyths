"""有界DNS解析；数字地址直接处理，不启动子进程。"""

import ipaddress
import json
import socket
import subprocess
import sys
import time

from .errors import ThsNetworkError

_WORKER = """
import json,socket,sys
rows=socket.getaddrinfo(sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)
print(json.dumps([(int(f),int(t),int(p),a) for f,t,p,c,a in rows]))
"""


def resolve(host: str, port: int, *, deadline: float) -> list[tuple[int, str]]:
    """返回数字地址；解析进程超时后由subprocess终止并回收。"""
    if not host or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid endpoint")
    if deadline <= time.monotonic():
        raise ThsNetworkError("transport: resolution timed out")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        return [(socket.AF_INET if address.version == 4 else socket.AF_INET6, host)]
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", _WORKER, host, str(port)],
            capture_output=True,
            check=True,
            timeout=max(0.001, deadline - time.monotonic()),
        )
        rows = json.loads(result.stdout)
        addresses = []
        for family, _, _, sockaddr in rows:
            if family in (socket.AF_INET, socket.AF_INET6):
                numeric = str(ipaddress.ip_address(sockaddr[0]))
                item = (int(family), numeric)
                if item not in addresses:
                    addresses.append(item)
        if not addresses or time.monotonic() >= deadline:
            raise ValueError("no usable address within deadline")
        return addresses
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, IndexError):
        raise ThsNetworkError("transport: resolution failed or timed out") from None
