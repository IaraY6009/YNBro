"""Receiver-side UDP exchange from the receiver feature branch."""

from __future__ import annotations

import socket
import time
from typing import Any

from ._protocol import (
    ADVERTISE,
    DETAIL,
    MAX_PACKET_SIZE,
    MessageError,
    START_PORT,
    decode_message,
    encode_message,
    make_ack,
    parse_advertisement,
    parse_detail,
    validate_ipv4,
    validate_port,
    validate_timeout,
)


def discover(
    timeout: float,
    *,
    start_port: int = START_PORT,
    bind_host: str = "0.0.0.0",
) -> dict[str, object] | None:
    """Receive and acknowledge one valid ADVERTISE/DETAIL exchange.

    The merged receiver branch did not implement the RTSP probe required to
    produce the SRS result dictionary, so a completed UDP exchange currently
    returns ``None`` after its DETAIL ACK.
    """

    timeout_value = validate_timeout(timeout)
    listen_port = validate_port(start_port)
    listen_host = validate_ipv4(bind_host)
    deadline = time.monotonic() + timeout_value

    sender_peer: tuple[str, int] | None = None
    device_id: str | None = None
    advertisement_id: str | None = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.bind((listen_host, listen_port))

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
                    message = decode_message(payload)
                except MessageError:
                    continue

                if sender_peer is None:
                    advertisement = _try_parse_advertisement(message)
                    if advertisement is None:
                        continue
                    try:
                        udp_socket.sendto(
                            encode_message(
                                make_ack(
                                    str(advertisement["device_id"]),
                                    ADVERTISE,
                                    message_id=advertisement["message_id"],
                                )
                            ),
                            peer,
                        )
                    except OSError:
                        continue
                    sender_peer = peer
                    device_id = str(advertisement["device_id"])
                    advertisement_id = str(advertisement["message_id"])
                    continue

                if peer != sender_peer:
                    continue
                detail = _try_parse_detail(message)
                if (
                    detail is None
                    or detail["device_id"] != device_id
                    or detail["message_id"] == advertisement_id
                ):
                    continue
                try:
                    udp_socket.sendto(
                        encode_message(
                            make_ack(
                                device_id,
                                DETAIL,
                                message_id=detail["message_id"],
                            )
                        ),
                        sender_peer,
                    )
                except OSError:
                    continue

                # RTSP URI construction and probe are intentionally left
                # unimplemented because neither merged feature branch has them.
                return None
    except (OSError, OverflowError):
        return None


def _try_parse_advertisement(
    message: dict[str, Any],
) -> dict[str, object] | None:
    try:
        return parse_advertisement(message)
    except MessageError:
        return None


def _try_parse_detail(message: dict[str, Any]) -> dict[str, object] | None:
    try:
        return parse_detail(message)
    except MessageError:
        return None
