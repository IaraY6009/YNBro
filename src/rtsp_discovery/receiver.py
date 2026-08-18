from __future__ import annotations

import json
import logging
import socket
import time
import uuid
from dataclasses import dataclass
from threading import Event
from typing import Any


logger = logging.getLogger(__name__)

DISCOVERY_PORT = 37020
MAX_PACKET_SIZE = 4096
PROTOCOL_VERSION = 1

ADVERTISE_TYPE = "ADVERTISE"
DETAIL_TYPE = "DETAIL"
ACK_TYPE = "ACK"


class ProtocolError(ValueError):
    """잘못된 UDP discovery 메시지를 나타내는 예외."""


@dataclass(frozen=True)
class ReceivedDevice:
    """수신한 RTSP 장치 정보."""

    message_type: str
    message_id: str
    device_id: str
    source_ip: str
    source_port: int
    ip: str | None = None
    rtsp_port: int | None = None
    mac: str | None = None
    stream_path: str | None = None

    @property
    def rtsp_url(self) -> str | None:
        """수신한 장치 정보를 RTSP URL로 변환한다."""
        if self.ip is None or self.rtsp_port is None:
            return None

        if self.stream_path:
            return (
                f"rtsp://{self.ip}:{self.rtsp_port}/"
                f"{self.stream_path.lstrip('/')}"
            )

        return f"rtsp://{self.ip}:{self.rtsp_port}"


def _decode_packet(data: bytes) -> dict[str, Any]:
    """UTF-8 JSON bytes를 dictionary로 변환한다."""
    try:
        packet = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(
            "UDP packet must be valid UTF-8 JSON"
        ) from exc

    if not isinstance(packet, dict):
        raise ProtocolError("UDP packet must be a JSON object")

    return packet


def _require_string(
    packet: dict[str, Any],
    field_name: str,
) -> str:
    """필수 문자열 필드를 검증한다."""
    value = packet.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(
            f"{field_name} must be a non-empty string"
        )

    return value


def _require_port(
    packet: dict[str, Any],
    field_name: str,
) -> int:
    """포트 번호를 검증한다."""
    value = packet.get(field_name)

    if not isinstance(value, int) or not 1 <= value <= 65535:
        raise ProtocolError(
            f"{field_name} must be between 1 and 65535"
        )

    return value


def parse_advertise_or_detail(
    data: bytes,
) -> dict[str, Any]:
    """
    ADVERTISE 또는 DETAIL 메시지를 검증하고 반환한다.
    """
    packet = _decode_packet(data)

    message_type = packet.get("type")

    if message_type not in {
        ADVERTISE_TYPE,
        DETAIL_TYPE,
    }:
        raise ProtocolError(
            "packet type must be ADVERTISE or DETAIL"
        )

    if packet.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")

    _require_string(packet, "message_id")
    _require_string(packet, "device_id")

    if message_type == ADVERTISE_TYPE:
        _require_string(packet, "ip")
        _require_port(packet, "rtsp_port")
        _require_string(packet, "mac")

    if message_type == DETAIL_TYPE:
        _require_string(packet, "stream_path")

    return packet


def make_ack(
    *,
    in_reply_to: str,
    receiver_id: str,
    status: str = "received",
) -> bytes:
    """수신한 메시지에 대한 ACK를 생성한다."""
    if not isinstance(in_reply_to, str) or not in_reply_to.strip():
        raise ValueError(
            "in_reply_to must be a non-empty string"
        )

    if not isinstance(receiver_id, str) or not receiver_id.strip():
        raise ValueError(
            "receiver_id must be a non-empty string"
        )

    if status not in {
        "received",
        "processed",
        "error",
    }:
        raise ValueError(
            "status must be received, processed, or error"
        )

    packet = {
        "type": ACK_TYPE,
        "version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "in_reply_to": in_reply_to,
        "receiver_id": receiver_id,
        "status": status,
    }

    return json.dumps(
        packet,
        separators=(",", ":"),
    ).encode("utf-8")


class RTSPAdvertisementReceiver:
    """
    UDP ADVERTISE와 DETAIL을 수신하고 ACK를 유니캐스트로 전송한다.

    처리 규칙:
    - 정상적인 ADVERTISE/DETAIL을 수신하면 ACK를 보낸다.
    - 중복 message_id를 수신해도 ACK는 다시 보낸다.
    - 중복 메시지의 실제 처리는 한 번만 한다.
    - ACK는 패킷에 들어 있는 IP가 아니라 실제 송신 주소로 보낸다.
    """

    def __init__(
        self,
        *,
        listen_port: int = DISCOVERY_PORT,
        receiver_id: str = "receiver-01",
        bind_address: str = "",
        duplicate_ttl: float = 60.0,
    ) -> None:
        if not 1 <= listen_port <= 65535:
            raise ValueError(
                "listen_port must be between 1 and 65535"
            )

        if not receiver_id.strip():
            raise ValueError(
                "receiver_id must not be empty"
            )

        if duplicate_ttl <= 0:
            raise ValueError(
                "duplicate_ttl must be greater than 0"
            )

        self.listen_port = listen_port
        self.receiver_id = receiver_id
        self.bind_address = bind_address
        self.duplicate_ttl = duplicate_ttl

        self._stop_event = Event()
        self._seen_messages: dict[str, float] = {}
        self._devices: dict[str, ReceivedDevice] = {}

    def stop(self) -> None:
        """수신 루프를 종료한다."""
        self._stop_event.set()

    def serve_forever(self) -> None:
        """UDP 수신을 계속 실행한다."""
        logger.info(
            "Receiver listening on %s:%d",
            self.bind_address or "0.0.0.0",
            self.listen_port,
        )

        with socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        ) as sock:
            sock.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_REUSEADDR,
                1,
            )
            sock.bind(
                (
                    self.bind_address,
                    self.listen_port,
                )
            )
            sock.settimeout(0.2)

            while not self._stop_event.is_set():
                try:
                    data, source_address = sock.recvfrom(
                        MAX_PACKET_SIZE
                    )
                except socket.timeout:
                    self._remove_expired_messages()
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break

                    logger.exception(
                        "UDP receive failed"
                    )
                    continue

                self._handle_packet(
                    sock=sock,
                    data=data,
                    source_address=source_address,
                )

    def get_devices(self) -> list[ReceivedDevice]:
        """현재까지 수신한 장치 목록을 반환한다."""
        return list(self._devices.values())

    def _handle_packet(
        self,
        *,
        sock: socket.socket,
        data: bytes,
        source_address: tuple[str, int],
    ) -> None:
        try:
            packet = parse_advertise_or_detail(data)
        except ProtocolError as exc:
            logger.warning(
                "Invalid packet from %s:%d: %s",
                source_address[0],
                source_address[1],
                exc,
            )
            return

        message_id = packet["message_id"]

        # 중복 메시지라도 ACK는 재전송한다.
        ack = make_ack(
            in_reply_to=message_id,
            receiver_id=self.receiver_id,
            status="received",
        )

        try:
            # 실제 UDP 송신자의 IP와 포트로 ACK를 전송한다.
            sock.sendto(ack, source_address)
        except OSError:
            logger.exception(
                "Failed to send ACK to %s:%d",
                source_address[0],
                source_address[1],
            )
            return

        if self._is_duplicate(message_id):
            logger.info(
                "Duplicate message ignored: %s",
                message_id,
            )
            return

        device = ReceivedDevice(
            message_type=packet["type"],
            message_id=message_id,
            device_id=packet["device_id"],
            source_ip=source_address[0],
            source_port=source_address[1],
            ip=packet.get("ip"),
            rtsp_port=packet.get("rtsp_port"),
            mac=packet.get("mac"),
            stream_path=packet.get("stream_path"),
        )

        self._devices[device.device_id] = device

        logger.info(
            "%s received: device_id=%s, message_id=%s",
            device.message_type,
            device.device_id,
            device.message_id,
        )

        if device.rtsp_url:
            logger.info(
                "RTSP URL: %s",
                device.rtsp_url,
            )

    def _is_duplicate(self, message_id: str) -> bool:
        now = time.monotonic()
        self._remove_expired_messages(now)

        if message_id in self._seen_messages:
            return True

        self._seen_messages[message_id] = now
        return False

    def _remove_expired_messages(
        self,
        now: float | None = None,
    ) -> None:
        current_time = (
            now if now is not None else time.monotonic()
        )
        expiration_time = current_time - self.duplicate_ttl

        expired_ids = [
            message_id
            for message_id, received_at
            in self._seen_messages.items()
            if received_at < expiration_time
        ]

        for message_id in expired_ids:
            del self._seen_messages[message_id]
