"""Sender-side ADVERTISE -> ACK -> DETAIL -> ACK exchange."""

from __future__ import annotations

import socket
import time
from typing import Any

from ._protocol import (
    ADVERTISE,
    MAX_PACKET_SIZE,
    MessageError,
    START_PORT,
    decode_message,
    encode_message,
    make_advertisement,
    make_detail,
    parse_ack,
    validate_ipv4,
    validate_port,
    validate_timeout,
)


def advertise(
    device_id: str,
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    *,
    timeout: float = 2.0,
    start_port: int = START_PORT,
    broadcast_address: str = "255.255.255.255",
) -> bool:
    """Perform the finite UDP bootstrap exchange for one Receiver."""

    timeout_value = validate_timeout(timeout)
    destination = (validate_ipv4(broadcast_address), validate_port(start_port))

    # Build both packets before creating a socket so invalid endpoint input is
    # rejected before any network activity.
    advertisement = make_advertisement(device_id)
    detail = make_detail(device_id, ip, rtsp_port, rtsp_path)
    advertisement_payload = encode_message(advertisement)
    detail_payload = encode_message(detail)
    deadline = time.monotonic() + timeout_value

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.bind(("0.0.0.0", 0))
            udp_socket.sendto(advertisement_payload, destination)

            receiver_peer = _wait_for_ack(
                udp_socket,
                deadline=deadline,
                device_id=device_id,
                ack_for=ADVERTISE,
                message_id=str(advertisement["message_id"]),
            )
            if receiver_peer is None:
                return False

            udp_socket.sendto(detail_payload, receiver_peer)

            # jinwoo did not implement receiving or validating the DETAIL ACK.
            # Do not report a successful exchange until that SRS requirement is
            # implemented separately.
            return False
    except (OSError, OverflowError):
        return False


def _wait_for_ack(
    udp_socket: socket.socket,
    *,
    deadline: float,
    device_id: str,
    ack_for: str,
    message_id: str,
) -> tuple[str, int] | None:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            udp_socket.settimeout(remaining)
            payload, peer = udp_socket.recvfrom(MAX_PACKET_SIZE)
        except (socket.timeout, TimeoutError):
            return None
        except (OSError, OverflowError):
            return None

        try:
            ack: dict[str, Any] = parse_ack(decode_message(payload))
        except MessageError:
            continue
        if (
            ack["device_id"] == device_id
            and ack["ack_for"] == ack_for
            and ack["message_id"] == message_id
        ):
            return peer
