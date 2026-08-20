"""RTSP endpoint helpers contributed by the receiver branch."""

from __future__ import annotations

import re
import socket
import time
from urllib.parse import quote

from ._protocol import (
    validate_ipv4,
    validate_port,
    validate_rtsp_path,
    validate_timeout,
)


# CODEX-GENERATED (Codex를 통해 생성된 코드): FR-RTSP-005/006 구현에
# 사용하는 엄격한 RTSP/2.0 status-line 규칙과 무한 header 수신 방지 상한이다.
_STATUS_LINE = re.compile(rb"^RTSP/2\.0 ([0-9]{3}) [\x20-\x7e]+$")
_MAX_RESPONSE_HEADER = 16_384


def build_rtsp_uri(ip: str, rtsp_port: int, rtsp_path: str) -> str:
    """Build the RTSP URI represented by a validated DETAIL endpoint."""

    host = validate_ipv4(ip)
    port = validate_port(rtsp_port)
    path = validate_rtsp_path(rtsp_path)
    return f"rtsp://{host}:{port}{quote(path, safe='/')}"


def probe_rtsp(
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    timeout: float,
) -> bool:
    """Return whether an RTSP/2.0 OPTIONS request receives a 2xx response."""

    # CODEX-GENERATED (Codex를 통해 생성된 코드): FR-RTSP-002~007 구현.
    # TCP 연결, OPTIONS/CSeq 전송, 하나의 timeout 예산, 엄격한 응답 판정과
    # 네트워크 오류 격리를 수행한다.
    timeout_value = validate_timeout(timeout)
    if timeout_value == 0:
        return False

    try:
        host = validate_ipv4(ip)
        port = validate_port(rtsp_port)
        path = validate_rtsp_path(rtsp_path)
        uri = build_rtsp_uri(host, port, path)
        request = (
            f"OPTIONS {uri} RTSP/2.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: ynb/0.0.1\r\n"
            "\r\n"
        ).encode("ascii")
    except (ValueError, UnicodeError):
        return False

    deadline = time.monotonic() + timeout_value
    response = bytearray()
    try:
        with socket.create_connection(
            (host, port), timeout=timeout_value
        ) as connection:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            connection.settimeout(remaining)
            connection.sendall(request)

            while b"\r\n\r\n" not in response and len(response) < _MAX_RESPONSE_HEADER:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                connection.settimeout(remaining)
                chunk = connection.recv(
                    min(4_096, _MAX_RESPONSE_HEADER - len(response))
                )
                if not chunk:
                    break
                response.extend(chunk)
    except (OSError, OverflowError, UnicodeError):
        return False

    if b"\r\n\r\n" not in response:
        return False
    status_line = bytes(response).split(b"\r\n", 1)[0]
    match = _STATUS_LINE.fullmatch(status_line)
    return bool(match and 200 <= int(match.group(1)) < 300)
