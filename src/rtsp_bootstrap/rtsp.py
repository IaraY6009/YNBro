"""Minimal RTSP/2.0 reachability probe."""

from __future__ import annotations

import math
import re
import socket
import time
from urllib.parse import quote

_STATUS_LINE = re.compile(r"^RTSP/2\.0 ([0-9]{3}) [^\r\n]*$")
_MAX_RESPONSE_HEADER = 16_384


def build_rtsp_uri(ip: str, port: int, path: str) -> str:
    """Build the RTSP URI represented by validated bootstrap fields."""

    encoded_path = quote(path, safe="/:@?&=+$,;%-._~!*'()[]")
    return f"rtsp://{ip}:{port}{encoded_path}"


def probe_rtsp(ip: str, port: int, path: str, timeout: float = 2.0) -> bool:
    """Return true only for a timely 2xx response to an RTSP/2.0 OPTIONS request."""

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout must be greater than zero")

    uri = build_rtsp_uri(ip, port, path)
    try:
        request = (
            f"OPTIONS {uri} RTSP/2.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: rtsp-bootstrap/0.1\r\n"
            "\r\n"
        ).encode("ascii")
    except UnicodeEncodeError:
        return False

    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((ip, port), timeout=timeout) as connection:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            connection.settimeout(remaining)
            connection.sendall(request)
            response = bytearray()
            while b"\r\n\r\n" not in response and len(response) < _MAX_RESPONSE_HEADER:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                connection.settimeout(remaining)
                chunk = connection.recv(min(4_096, _MAX_RESPONSE_HEADER - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
    except (OSError, UnicodeError):
        return False

    if b"\r\n\r\n" not in response:
        return False
    header_block = bytes(response).split(b"\r\n\r\n", 1)[0]
    lines = header_block.split(b"\r\n")
    try:
        status_line = lines[0].decode("ascii")
        headers: dict[str, str] = {}
        for raw_line in lines[1:]:
            name, separator, value = raw_line.partition(b":")
            if not separator:
                return False
            headers[name.decode("ascii").strip().lower()] = value.decode("ascii").strip()
    except UnicodeDecodeError:
        return False
    match = _STATUS_LINE.match(status_line)
    return bool(
        match
        and 200 <= int(match.group(1)) < 300
        and headers.get("cseq") == "1"
    )
