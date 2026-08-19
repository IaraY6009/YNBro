"""YNB Receiver의 일회성 동기식 장비 발견을 구현한다.

유효한 ADVERTISE 한 건을 선택해 실제 발신 peer로 ACK를 보내고, 같은
peer와 device ID의 DETAIL만 수락한다. DETAIL을 확인한 뒤 RTSP/2.0
probe를 수행하고 endpoint와 연결 결과를 하나의 dict로 반환한다.
"""

from __future__ import annotations

import socket
import time
from typing import Any

from . import connecter
from ._protocol import (
    ADVERTISE,
    DEFAULT_START_PORT,
    DETAIL,
    MAX_DATAGRAM_SIZE,
    MessageError,
    decode_message,
    encode_message,
    make_ack,
    parse_advertisement,
    parse_detail,
    validate_port,
    validate_timeout,
)


def _receive_message(
    udp_socket: socket.socket, deadline: float
) -> tuple[dict[str, Any], tuple[str, int]] | None:
    """deadline 안에서 올바른 UTF-8 JSON 데이터그램 하나를 수신한다.

    ``recvfrom()``이 알려 준 실제 발신 주소를 peer로 함께 반환한다.
    JSON 형식이 잘못된 데이터그램은 Receiver를 끝내지 않고 무시하며,
    deadline 만료 또는 socket 오류이면 ``None``을 반환한다. 메시지 종류별
    필드 검증은 호출한 단계의 ``parse_*`` 함수가 이어서 수행한다.
    """

    while True:
        # 호출 전체가 같은 절대 deadline을 사용하므로, 잘못된 패킷이 계속
        # 들어와도 discover()의 총 실행 시간이 계속 연장되지 않는다.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            udp_socket.settimeout(remaining)
            # 한도보다 한 바이트 크게 받아 oversized datagram을 정상 메시지로
            # 잘라서 처리하지 않고 decode_message()가 크기 오류로 거부하게 한다.
            payload, raw_peer = udp_socket.recvfrom(MAX_DATAGRAM_SIZE + 1)
        except socket.timeout:
            return None
        except (OSError, OverflowError):
            # Python float로는 유효해도 OS socket timeout 범위를 넘을 수 있다.
            return None

        peer = (str(raw_peer[0]), int(raw_peer[1]))
        try:
            return decode_message(payload), peer
        except MessageError:
            # SRS FR-RCV-008: 잘못된 UDP 입력 하나가 전체 Receiver를
            # 종료시키지 않아야 하므로 다음 데이터그램을 계속 기다린다.
            continue


def discover(
    timeout: float = 5,
    *,
    start_port: int = DEFAULT_START_PORT,
    bind_host: str = "0.0.0.0",
) -> dict[str, Any] | None:
    """Sender 한 대를 발견하고 RTSP probe 결과를 반환한다.

    Args:
        timeout: ADVERTISE/DETAIL 교환과 RTSP probe를 모두 포함한 최대 시간.
        start_port: ADVERTISE를 수신할 UDP bootstrap port.
        bind_host: 수신 socket을 bind할 IPv4 host. ``0.0.0.0``은 모든
            로컬 IPv4 인터페이스에서 수신한다는 뜻이다.

    Returns:
        정상 DETAIL까지 받으면 ``device_id``, endpoint, ``rtsp_uri``,
        ``rtsp_connected``를 담은 dict를 반환한다. RTSP probe가 실패해도
        정보 교환이 완료되었다면 dict를 반환하고 ``rtsp_connected``만
        ``False``가 된다. UDP 교환 미완료나 socket 오류에서는 ``None``이다.

    Raises:
        ValueError: timeout, port 또는 bind host 타입이 잘못된 경우.

    한 호출은 첫 번째 유효 ADVERTISE의 Sender 한 대만 처리한다. 여러 장비를
    누적 관리하는 registry는 SRS 0.0.1의 범위 밖이다.
    """

    timeout_value = validate_timeout(timeout)
    listen_port = validate_port(start_port)
    if not isinstance(bind_host, str):
        raise ValueError("bind_host는 문자열이어야 합니다")

    # 두 번의 UDP 교환과 RTSP probe가 하나의 시간 예산을 공유한다.
    deadline = time.monotonic() + timeout_value

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.bind((bind_host, listen_port))

            # 1단계: 최초의 유효한 ADVERTISE를 선택한다. payload에 들어 있는
            # 주소가 아니라 recvfrom()의 실제 peer와 device ID를 이후 상대 정보로 고정한다.
            sender_peer: tuple[str, int] | None = None
            sender_device_id: str | None = None
            while sender_peer is None:
                received = _receive_message(udp_socket, deadline)
                if received is None:
                    return None
                message, peer = received
                try:
                    advertisement = parse_advertisement(message)
                except MessageError:
                    continue
                udp_socket.sendto(
                    encode_message(make_ack(advertisement["device_id"], ADVERTISE)),
                    peer,
                )
                sender_peer = peer
                sender_device_id = advertisement["device_id"]

            # 2단계: 다른 peer의 DETAIL이나 device ID가 다른 DETAIL은 무시한다.
            # 동시에 여러 Sender가 광고하더라도 서로의 endpoint가 섞이지 않는다.
            while True:
                received = _receive_message(udp_socket, deadline)
                if received is None:
                    return None
                message, peer = received
                if peer != sender_peer:
                    continue
                try:
                    detail = parse_detail(message)
                except MessageError:
                    continue
                if detail["device_id"] != sender_device_id:
                    continue

                # SRS 순서상 DETAIL ACK를 먼저 보내고 RTSP probe를 수행한다.
                # 느린 RTSP 서버 때문에 Sender의 ACK 대기가 지연되어서는 안 된다.
                udp_socket.sendto(
                    encode_message(make_ack(detail["device_id"], DETAIL)),
                    peer,
                )
                # probe에도 discover() 전체 deadline의 남은 시간만 배정한다.
                remaining = max(0.0, deadline - time.monotonic())
                connected = connecter.probe_rtsp(
                    detail["ip"],
                    detail["rtsp_port"],
                    detail["rtsp_path"],
                    timeout=remaining,
                )
                return {
                    "device_id": detail["device_id"],
                    "ip": detail["ip"],
                    "rtsp_port": detail["rtsp_port"],
                    "rtsp_path": detail["rtsp_path"],
                    "rtsp_uri": connecter.build_rtsp_uri(
                        detail["ip"], detail["rtsp_port"], detail["rtsp_path"]
                    ),
                    "rtsp_connected": connected,
                }
    except OSError:
        # bind 실패나 ACK 전송 실패를 발견 결과 없음으로 처리한다. RTSP
        # 실패와 달리 이 정책은 향후 공개 오류 모델을 정할 때 세분화할 수 있다.
        return None
