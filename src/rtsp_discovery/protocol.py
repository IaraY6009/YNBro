import json
from typing import Any

DISCOVERY_PORT = 37020
PROTOCOL_VERSION = 1
REQUEST_TYPE = "rtsp_discovery_request"
RESPONSE_TYPE = "rtsp_discovery_response"
MAX_PACKET_SIZE = 4096


class ProtocolError(ValueError):
    pass


def make_request(packet_number: int = 0) -> bytes:
    if packet_number < 0:
        raise ProtocolError("packet_number must be greater than or equal to 0")

    return _encode(
        {
            "type": REQUEST_TYPE,
            "version": PROTOCOL_VERSION,
            "packet_number": packet_number,
        }
    )


def make_response(ip: str, port: int, mac: str, packet_number: int) -> bytes:
    if not ip:
        raise ProtocolError("ip is required")
    if not (0 < port <= 65535):
        raise ProtocolError("port must be between 1 and 65535")
    if not mac:
        raise ProtocolError("mac is required")
    if packet_number < 0:
        raise ProtocolError("packet_number must be greater than or equal to 0")

    return _encode(
        {
            "type": RESPONSE_TYPE,
            "version": PROTOCOL_VERSION,
            "ip": ip,
            "port": port,
            "mac": mac,
            "packet_number": packet_number,
        }
    )


def parse_request(data: bytes) -> dict[str, Any]:
    packet = _decode(data)
    if packet.get("type") != REQUEST_TYPE:
        raise ProtocolError("unexpected packet type")
    if packet.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")

    packet_number = packet.get("packet_number")
    if not isinstance(packet_number, int) or packet_number < 0:
        raise ProtocolError(
            "request packet_number must be an integer greater than or equal to 0"
        )

    return packet


def parse_response(data: bytes) -> dict[str, Any]:
    packet = _decode(data)
    if packet.get("type") != RESPONSE_TYPE:
        raise ProtocolError("unexpected packet type")
    if packet.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")

    ip = packet.get("ip")
    port = packet.get("port")
    mac = packet.get("mac")
    packet_number = packet.get("packet_number")
    if not isinstance(ip, str) or not ip:
        raise ProtocolError("response ip must be a non-empty string")
    if not isinstance(port, int) or not (0 < port <= 65535):
        raise ProtocolError("response port must be an integer between 1 and 65535")
    if not isinstance(mac, str) or not mac:
        raise ProtocolError("response mac must be a non-empty string")
    if not isinstance(packet_number, int) or packet_number < 0:
        raise ProtocolError(
            "response packet_number must be an integer greater than or equal to 0"
        )

    return packet


def _encode(packet: dict[str, Any]) -> bytes:
    return json.dumps(packet, separators=(",", ":")).encode("utf-8")


def _decode(data: bytes) -> dict[str, Any]:
    try:
        packet = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("packet must be valid utf-8 JSON") from exc

    if not isinstance(packet, dict):
        raise ProtocolError("packet must be a JSON object")
    return packet
