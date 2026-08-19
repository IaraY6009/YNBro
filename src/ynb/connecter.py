"""RTSP URI 생성과 최소한의 RTSP/2.0 연결 확인을 담당한다.

probe는 TCP 연결 후 OPTIONS 요청에 2xx 응답이 오는지만 확인한다.
이는 RTSP 제어 연결이 응답한다는 뜻이며, 영상 스트림의 존재나
DESCRIBE, SETUP, PLAY 성공까지 보장하지는 않는다.
"""

from __future__ import annotations

import re
import socket
import time
from urllib.parse import quote

from ._protocol import validate_endpoint, validate_timeout

# 응답 첫 줄은 RTSP/2.0, 세 자리 상태 코드, 출력 가능한 ASCII reason
# phrase를 각각 한 칸으로 구분해야 한다. 제어 문자가 섞인 응답은 거부한다.
_STATUS_LINE = re.compile(rb"^RTSP/2\.0 ([0-9]{3}) [\x20-\x7e]+$")

# 잘못된 서버가 header 종료 없이 끝없이 데이터를 보내는 상황을 막기 위해
# 응답 header는 16 KiB까지만 읽는다.
_MAX_RESPONSE_HEADER = 16_384


def build_rtsp_uri(ip: str, port: int, path: str) -> str:
    """검증된 IPv4 endpoint를 RTSP URI 문자열로 조합한다.

    URI에 직접 넣을 수 없는 path 문자는 UTF-8 percent encoding한다.
    따라서 한글이나 공백이 포함된 경로도 RTSP 요청 행 전체를 ASCII로
    안전하게 전송할 수 있다.

    Raises:
        ValueError: IP, port 또는 path 형식이 잘못된 경우.
    """

    normalized_ip, normalized_port, normalized_path = validate_endpoint(ip, port, path)
    encoded_path = quote(normalized_path, safe="/:@?&=+$,;%-._~!*'()[]")
    return f"rtsp://{normalized_ip}:{normalized_port}{encoded_path}"


def probe_rtsp(ip: str, port: int, path: str, timeout: float = 2.0) -> bool:
    """RTSP/2.0 OPTIONS 요청이 2xx 응답을 받는지 확인한다.

    Args:
        ip: DETAIL로 전달받은 RTSP 서버의 IPv4 주소.
        port: RTSP 서버의 TCP port.
        path: ``/``로 시작하는 RTSP 경로.
        timeout: TCP 연결, 요청 송신, 응답 수신 전체에 사용할 시간(초).

    Returns:
        완전한 RTSP/2.0 header의 status code가 2xx이면 ``True``다.
        timeout이 0이거나 연결 거부, 응답 timeout, 잘못된 응답이면
        처리되지 않은 예외를 밖으로 보내지 않고 ``False``를 반환한다.

    Raises:
        ValueError: timeout 자체가 음수, NaN, 무한대 또는 bool인 경우.
    """

    timeout_value = validate_timeout(timeout)
    if timeout_value == 0:
        return False

    try:
        uri = build_rtsp_uri(ip, port, path)
        # RTSP의 각 행은 CRLF(\r\n)로 끝난다. CSeq는 요청 순서를 식별하는
        # 필수 header이며, 마지막 빈 줄이 header의 끝을 나타낸다.
        request = (
            f"OPTIONS {uri} RTSP/2.0\r\n"
            "CSeq: 1\r\n"
            "User-Agent: ynb/0.0.1\r\n"
            "\r\n"
        ).encode("ascii")
    except (ValueError, UnicodeError):
        return False

    # TCP 연결, 요청 송신, 응답 수신이 하나의 시간 예산을 공유한다.
    # monotonic clock은 시스템 시각이 바뀌어도 경과 시간 계산이 흔들리지 않는다.
    deadline = time.monotonic() + timeout_value
    response = bytearray()
    try:
        with socket.create_connection((ip, port), timeout=timeout_value) as connection:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            connection.settimeout(remaining)
            connection.sendall(request)
            # TCP는 UDP 데이터그램과 달리 경계가 없는 byte stream이다. 한 번의
            # recv()가 RTSP 응답 하나와 일치한다고 가정하지 않고, header 종료
            # 표시인 CRLF CRLF가 나타날 때까지 여러 조각을 이어 붙인다.
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
        # timeout, 연결 거부, 연결 초기화 등은 정상적인 probe 실패다.
        # 매우 큰 timeout의 OS 시간 변환 실패(OverflowError)도 같은 의미다.
        # SRS에 따라 Receiver 밖으로 처리되지 않은 네트워크 예외를 보내지 않는다.
        return False

    if b"\r\n\r\n" not in response:
        return False
    # OPTIONS 응답 본문은 필요하지 않으며 첫 status line만 판정한다.
    status_line = bytes(response).split(b"\r\n", 1)[0]
    match = _STATUS_LINE.fullmatch(status_line)
    return bool(match and 200 <= int(match.group(1)) < 300)
