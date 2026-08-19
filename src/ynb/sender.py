"""YNB Sender의 일회성 동기식 bootstrap 교환을 구현한다.

ADVERTISE만 IPv4 broadcast로 보내고, 이후에는 ACK를 보낸 Receiver의
실제 UDP peer에 DETAIL을 unicast한다. 전체 교환은 함수에 전달한 하나의
timeout 안에서 끝나며 메시지 재전송은 SRS 0.0.1 범위에 포함되지 않는다.
"""

from __future__ import annotations

import socket
import time

from ._protocol import (
    ADVERTISE,
    DEFAULT_BROADCAST_ADDRESS,
    DEFAULT_START_PORT,
    DETAIL,
    MAX_DATAGRAM_SIZE,
    MessageError,
    decode_message,
    encode_message,
    make_advertisement,
    make_detail,
    parse_ack,
    validate_ipv4,
    validate_port,
    validate_timeout,
)


def _wait_for_ack(
    udp_socket: socket.socket,
    *,
    deadline: float,
    device_id: str,
    ack_for: str,
    expected_peer: tuple[str, int] | None = None,
) -> tuple[str, int] | None:
    """마감 시각까지 조건에 맞는 ACK를 기다리고 발신 peer를 반환한다.

    ``recvfrom()``이 돌려주는 peer는 데이터그램을 실제로 보낸
    ``(IPv4 주소, UDP port)``다. 형식, device ID, ``ack_for``가 맞지 않는
    데이터그램은 무시한다. ``expected_peer``가 주어지면 이전 단계에서
    선택한 Receiver가 보낸 ACK만 허용한다.

    이 peer 비교는 두 단계의 통신 상대가 같은지 확인할 뿐, 암호학적인
    발신자 인증을 제공하지는 않는다.
    """

    while True:
        # 각 패킷마다 timeout을 새로 시작하지 않고, 함수 전체가 공유하는
        # 절대 deadline에서 남은 시간만 계산한다. 따라서 잘못된 패킷이
        # 계속 도착하더라도 호출 시간이 무한히 늘어나지 않는다.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            udp_socket.settimeout(remaining)
            payload, raw_peer = udp_socket.recvfrom(MAX_DATAGRAM_SIZE + 1)
        except socket.timeout:
            return None
        except (OSError, OverflowError):
            # 매우 큰 유한 timeout도 운영체제의 시간 표현 범위를 넘을 수 있다.
            # 이 경우 ACK를 기다릴 수 없는 정상적인 socket 실패로 처리한다.
            return None

        # payload 안의 IP가 아니라 운영체제가 보고한 실제 UDP peer를 쓴다.
        peer = (str(raw_peer[0]), int(raw_peer[1]))
        if expected_peer is not None and peer != expected_peer:
            continue
        try:
            ack = parse_ack(decode_message(payload))
        except MessageError:
            continue
        if ack["device_id"] == device_id and ack["ack_for"] == ack_for:
            return peer


def advertise(
    device_id: str,
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    timeout: float = 5,
    *,
    start_port: int = DEFAULT_START_PORT,
    broadcast_address: str = DEFAULT_BROADCAST_ADDRESS,
    bind_host: str = "0.0.0.0",
    bind_port: int = 0,
) -> bool:
    """ADVERTISE → ACK → DETAIL → ACK 교환을 한 번 수행한다.

    Args:
        device_id: Sender를 식별하는 MAC 주소 문자열.
        ip: Receiver에 알릴 RTSP 서버의 IPv4 주소.
        rtsp_port: RTSP 서버가 수신하는 TCP port.
        rtsp_path: ``/``로 시작하는 RTSP 자원 경로.
        timeout: 두 UDP 왕복 전체에 사용할 최대 시간(초).
        start_port: ADVERTISE를 보낼 UDP bootstrap port.
        broadcast_address: ADVERTISE 목적지 IPv4 broadcast 주소.
        bind_host: 로컬 UDP socket을 bind할 IPv4 host. ``0.0.0.0``은
            사용 가능한 모든 로컬 IPv4 인터페이스를 뜻한다.
        bind_port: 로컬 source port. 0이면 운영체제가 임시 port를 고른다.

    Returns:
        DETAIL ACK까지 받으면 ``True``다. 이는 Receiver가 UDP 메시지를
        받았다는 뜻이며, 이후 Receiver의 RTSP probe 성공을 보장하지 않는다.
        timeout 또는 UDP socket 오류가 발생하면 ``False``다.

    Raises:
        ValueError: MAC, endpoint, timeout 또는 port 설정이 잘못된 경우.
        MessageError: JSON 직렬화 또는 datagram 크기 제한을 위반한 경우.
    """

    advertisement = make_advertisement(device_id)
    detail = make_detail(device_id, ip, rtsp_port, rtsp_path)
    # 소켓을 열기 전에 두 메시지를 모두 검증하고 직렬화한다. 따라서 endpoint가
    # 잘못되었거나 payload가 너무 큰 경우 ADVERTISE만 나가는 부분 교환이 없다.
    advertisement_payload = encode_message(advertisement)
    detail_payload = encode_message(detail)
    timeout_value = validate_timeout(timeout)
    destination_port = validate_port(start_port)
    destination_address = validate_ipv4(
        broadcast_address, field="broadcast_address"
    )
    local_port = validate_port(bind_port, allow_zero=True)
    if not isinstance(bind_host, str):
        raise ValueError("bind_host는 문자열이어야 합니다")

    deadline = time.monotonic() + timeout_value
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            # broadcast 주소로 sendto()하려면 SO_BROADCAST를 명시적으로 켜야 한다.
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.bind((bind_host, local_port))
            udp_socket.sendto(
                advertisement_payload,
                (destination_address, destination_port),
            )

            receiver_peer = _wait_for_ack(
                udp_socket,
                deadline=deadline,
                device_id=advertisement["device_id"],
                ack_for=ADVERTISE,
            )
            if receiver_peer is None:
                return False

            # 첫 ACK의 실제 발신 주소가 이후 DETAIL의 unicast 목적지다.
            udp_socket.sendto(detail_payload, receiver_peer)
            # DETAIL ACK도 같은 peer에서 와야 하나의 Receiver와 교환한 것이다.
            return (
                _wait_for_ack(
                    udp_socket,
                    deadline=deadline,
                    device_id=advertisement["device_id"],
                    ack_for=DETAIL,
                    expected_peer=receiver_peer,
                )
                is not None
            )
    except OSError:
        # UDP socket 생성, bind, send/receive 실패는 교환 실패(False)로
        # 통일한다. RTSP 성공 여부는 Receiver가 별도로 판단한다.
        return False
