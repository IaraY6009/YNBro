"""Wire-format helpers for the RTSP bootstrap protocol."""

from __future__ import annotations

import copy
import ipaddress
import json
import uuid
from enum import Enum
from typing import Any, Mapping

PROTOCOL_VERSION = "1.0"
MAX_DATAGRAM_SIZE = 65_507
_MAX_IDENTIFIER_LENGTH = 256
_MAX_PATH_LENGTH = 2_048


class MessageError(ValueError):
    """Raised when a bootstrap message is malformed or unsupported."""


class MessageType(str, Enum):
    """Supported bootstrap message types."""

    ADVERTISE = "ADVERTISE"
    DETAIL = "DETAIL"
    ACK = "ACK"


_REQUIRED_FIELDS = {
    "protocol_version",
    "message_type",
    "device_id",
    "message_id",
    "ip",
    "rtsp_port",
    "rtsp_path",
}


def _nonempty_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MessageError(f"{field} must be a non-empty string")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        raise MessageError(f"{field} is too long")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MessageError(f"{field} must contain valid Unicode") from exc
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def validate_message(message: Mapping[str, object]) -> dict[str, Any]:
    """Validate and return an isolated, normalized message dictionary."""

    if not isinstance(message, Mapping):
        raise MessageError("message must be a JSON object")

    missing = sorted(_REQUIRED_FIELDS.difference(message))
    if missing:
        raise MessageError(f"missing required fields: {', '.join(missing)}")

    normalized = copy.deepcopy(dict(message))
    if normalized["protocol_version"] != PROTOCOL_VERSION:
        raise MessageError("unsupported protocol_version")

    raw_type = normalized["message_type"]
    if isinstance(raw_type, MessageType):
        raw_type = raw_type.value
    try:
        message_type = MessageType(raw_type)
    except (TypeError, ValueError) as exc:
        raise MessageError("unsupported message_type") from exc
    normalized["message_type"] = message_type.value

    normalized["device_id"] = _nonempty_identifier(
        normalized["device_id"], "device_id"
    )
    normalized["message_id"] = _nonempty_identifier(
        normalized["message_id"], "message_id"
    )

    raw_ip = normalized["ip"]
    if not isinstance(raw_ip, str):
        raise MessageError("ip must be an IPv4 string")
    try:
        normalized["ip"] = str(ipaddress.IPv4Address(raw_ip))
    except ipaddress.AddressValueError as exc:
        raise MessageError("ip must be a valid IPv4 address") from exc

    port = normalized["rtsp_port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
        raise MessageError("rtsp_port must be an integer from 1 to 65535")

    path = normalized["rtsp_path"]
    if not isinstance(path, str) or not path.startswith("/"):
        raise MessageError("rtsp_path must be a string beginning with '/'")
    if len(path) > _MAX_PATH_LENGTH:
        raise MessageError("rtsp_path is too long")
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in path
    ):
        raise MessageError("rtsp_path must not contain whitespace or control characters")
    try:
        path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise MessageError("rtsp_path must contain valid Unicode") from exc

    if message_type is MessageType.DETAIL:
        details = normalized.get("details")
        if not isinstance(details, Mapping):
            raise MessageError("DETAIL requires a details object")
        normalized["details"] = copy.deepcopy(dict(details))
        normalized["in_reply_to"] = _nonempty_identifier(
            normalized.get("in_reply_to"), "in_reply_to"
        )
    elif message_type is MessageType.ACK:
        normalized["ack_for"] = _nonempty_identifier(
            normalized.get("ack_for"), "ack_for"
        )

    # This also validates arbitrary DETAIL values, extra fields, key types,
    # finite numbers, recursive objects, and lone Unicode surrogates.
    try:
        json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise MessageError("message contains a non-JSON value") from exc

    return normalized


def make_message(
    message_type: MessageType | str,
    *,
    device_id: str,
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    message_id: str | None = None,
    **extra: object,
) -> dict[str, Any]:
    """Build a validated protocol message with a generated ID by default."""

    message: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": (
            message_type.value if isinstance(message_type, MessageType) else message_type
        ),
        "device_id": device_id,
        "message_id": str(uuid.uuid4()) if message_id is None else message_id,
        "ip": ip,
        "rtsp_port": rtsp_port,
        "rtsp_path": rtsp_path,
    }
    message.update(extra)
    return validate_message(message)


def encode_message(message: Mapping[str, object]) -> bytes:
    """Serialize a valid message as compact UTF-8 JSON for a UDP datagram."""

    normalized = validate_message(message)
    try:
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise MessageError("message contains a non-JSON value") from exc
    if len(payload) > MAX_DATAGRAM_SIZE:
        raise MessageError("encoded message is too large for one UDP datagram")
    return payload


def decode_message(payload: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Decode and validate one UTF-8 JSON datagram."""

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise MessageError("payload must be bytes-like")
    raw_payload = bytes(payload)
    if not raw_payload:
        raise MessageError("payload is empty")
    if len(raw_payload) > MAX_DATAGRAM_SIZE:
        raise MessageError("payload is too large")
    try:
        document = json.loads(
            raw_payload.decode("utf-8"), parse_constant=_reject_json_constant
        )
        if not isinstance(document, dict):
            raise MessageError("message must be a JSON object")
        return validate_message(document)
    except MessageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise MessageError("payload is not valid UTF-8 JSON") from exc
