"""YNB 0.0.1 UDP wire protocol의 메시지 생성과 검증을 담당한다.

모든 wire 메시지는 UTF-8 JSON 객체 하나이며 UDP 데이터그램 하나에
완전히 들어가야 한다. 이 모듈은 Sender와 Receiver가 같은 필드 규칙을
사용하도록 메시지 생성, 파싱, 직렬화 기능을 한곳에 모아 둔다.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
from collections.abc import Mapping
from typing import Any

# ``255.255.255.255``는 현재 IPv4 broadcast domain에만 전달되는
# limited broadcast 주소다. 일반적인 라우터는 이 패킷을 다른 subnet으로
# 전달하지 않으므로 SRS가 정한 "동일 LAN 발견" 범위와 맞는다.
DEFAULT_START_PORT = 37_020
DEFAULT_BROADCAST_ADDRESS = "255.255.255.255"

# IPv4 UDP payload의 이론상 최대 크기는 전체 65,535바이트에서
# IPv4 기본 헤더 20바이트와 UDP 헤더 8바이트를 뺀 65,507바이트다.
# YNB 0.0.1은 메시지 분할을 지원하지 않으므로 이 크기를 넘으면 거부한다.
MAX_DATAGRAM_SIZE = 65_507

ADVERTISE = "ADVERTISE"
ACK = "ACK"
DETAIL = "DETAIL"

_MAC_ADDRESS = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\Z")
_ADVERTISE_FIELDS = frozenset({"message_type", "device_id"})
_ACK_FIELDS = frozenset({"message_type", "device_id", "ack_for"})
_DETAIL_FIELDS = frozenset(
    {"message_type", "device_id", "ip", "rtsp_port", "rtsp_path"}
)


class MessageError(ValueError):
    """메시지가 YNB 0.0.1 wire 계약에 맞지 않을 때 발생하는 예외."""


def validate_timeout(value: object) -> float:
    """timeout을 유한한 0 이상의 실수로 정규화한다.

    Python에서는 ``bool``이 ``int``의 하위 타입이지만, ``True``를 1초로
    해석하는 것은 사용자의 실수를 숨기므로 명시적으로 거부한다.
    """

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("timeout은 유한한 0 이상의 숫자여야 합니다")
    return float(value)


def validate_port(value: object, *, allow_zero: bool = False) -> int:
    """TCP/UDP port 번호를 검증한다.

    ``allow_zero=True``는 목적지 port를 0으로 쓰기 위한 옵션이 아니다.
    로컬 UDP socket을 bind할 때 운영체제가 임시 source port를 선택하도록
    요청하는 경우에만 0을 허용한다.
    """

    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= 65_535
    ):
        range_text = "0..65535" if allow_zero else "1..65535"
        raise ValueError(f"port는 {range_text} 범위의 정수여야 합니다")
    return value


def validate_device_id(value: object) -> str:
    """0.0.1의 장비 식별자인 MAC 주소 문자열을 검증한다."""

    if not isinstance(value, str) or _MAC_ADDRESS.fullmatch(value) is None:
        raise ValueError(
            "device_id는 AA:BB:CC:DD:EE:FF 형식의 MAC 주소여야 합니다"
        )
    return value


def validate_ipv4(value: object, *, field: str = "ip") -> str:
    """IPv4 문자열을 검증하고 표준 표기 문자열로 반환한다."""

    if not isinstance(value, str):
        raise ValueError(f"{field}는 IPv4 주소여야 합니다")
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{field}는 IPv4 주소여야 합니다") from exc


def validate_rtsp_path(value: object) -> str:
    """RTSP path의 기본 형식과 wire 안전성을 확인한다.

    path는 URI의 경로이므로 ``/``로 시작해야 한다. 제어 문자를 허용하면
    RTSP 요청 행에 의도하지 않은 줄바꿈이나 header가 들어갈 수 있으므로
    함께 차단한다.
    """

    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError("rtsp_path는 '/'로 시작하는 문자열이어야 합니다")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("rtsp_path에는 제어 문자를 사용할 수 없습니다")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("rtsp_path는 올바른 Unicode 문자열이어야 합니다") from exc
    return value


def validate_endpoint(ip: object, port: object, path: object) -> tuple[str, int, str]:
    """RTSP endpoint의 IP, port, path를 한 번에 검증하고 정규화한다."""

    return (
        validate_ipv4(ip),
        validate_port(port),
        validate_rtsp_path(path),
    )


def make_advertisement(device_id: object) -> dict[str, Any]:
    """endpoint를 노출하지 않는 최소 ADVERTISE 메시지를 만든다."""

    return {"message_type": ADVERTISE, "device_id": validate_device_id(device_id)}


def make_ack(device_id: object, ack_for: object) -> dict[str, Any]:
    """ADVERTISE 또는 DETAIL 수신을 확인하는 ACK 메시지를 만든다."""

    normalized_device_id = validate_device_id(device_id)
    if not isinstance(ack_for, str) or ack_for not in (ADVERTISE, DETAIL):
        raise ValueError("ack_for는 ADVERTISE 또는 DETAIL이어야 합니다")
    return {
        "message_type": ACK,
        "device_id": normalized_device_id,
        "ack_for": ack_for,
    }


def make_detail(
    device_id: object,
    ip: object,
    rtsp_port: object,
    rtsp_path: object,
) -> dict[str, Any]:
    """검증된 RTSP endpoint를 포함하는 DETAIL 메시지를 만든다."""

    normalized_ip, normalized_port, normalized_path = validate_endpoint(
        ip, rtsp_port, rtsp_path
    )
    return {
        "message_type": DETAIL,
        "device_id": validate_device_id(device_id),
        "ip": normalized_ip,
        "rtsp_port": normalized_port,
        "rtsp_path": normalized_path,
    }


def _require_fields(message: Mapping[str, object], fields: frozenset[str]) -> None:
    """메시지 필드가 0.0.1 계약과 정확히 같은지 확인한다.

    필수 필드 누락뿐 아니라 정의되지 않은 추가 필드도 거부한다. 이를 통해
    ``message_id`` 등을 쓰는 다른 protocol 버전과 0.0.1이 섞이는 것을 막는다.
    """

    if set(message) != fields:
        raise MessageError("메시지 필드가 YNB 0.0.1 계약과 일치하지 않습니다")


def parse_advertisement(message: Mapping[str, object]) -> dict[str, Any]:
    """수신 JSON 객체를 검증된 ADVERTISE 메시지로 해석한다."""

    if not isinstance(message, Mapping):
        raise MessageError("메시지는 JSON 객체여야 합니다")
    _require_fields(message, _ADVERTISE_FIELDS)
    if message.get("message_type") != ADVERTISE:
        raise MessageError("message_type은 ADVERTISE여야 합니다")
    try:
        return make_advertisement(message.get("device_id"))
    except ValueError as exc:
        raise MessageError(str(exc)) from exc


def parse_ack(message: Mapping[str, object]) -> dict[str, Any]:
    """수신 JSON 객체를 검증된 ACK 메시지로 해석한다."""

    if not isinstance(message, Mapping):
        raise MessageError("메시지는 JSON 객체여야 합니다")
    _require_fields(message, _ACK_FIELDS)
    if message.get("message_type") != ACK:
        raise MessageError("message_type은 ACK여야 합니다")
    try:
        return make_ack(message.get("device_id"), message.get("ack_for"))
    except ValueError as exc:
        raise MessageError(str(exc)) from exc


def parse_detail(message: Mapping[str, object]) -> dict[str, Any]:
    """수신 JSON 객체를 검증된 DETAIL 메시지로 해석한다."""

    if not isinstance(message, Mapping):
        raise MessageError("메시지는 JSON 객체여야 합니다")
    _require_fields(message, _DETAIL_FIELDS)
    if message.get("message_type") != DETAIL:
        raise MessageError("message_type은 DETAIL이어야 합니다")
    try:
        return make_detail(
            message.get("device_id"),
            message.get("ip"),
            message.get("rtsp_port"),
            message.get("rtsp_path"),
        )
    except ValueError as exc:
        raise MessageError(str(exc)) from exc


def encode_message(message: Mapping[str, object]) -> bytes:
    """메시지를 UDP에 실을 UTF-8 JSON payload로 직렬화한다.

    NaN과 무한대처럼 표준 JSON에 속하지 않는 값, 올바르지 않은 Unicode,
    UDP 한 데이터그램의 최대 크기를 넘는 결과는 ``MessageError``로 거부한다.
    """

    try:
        payload = json.dumps(
            dict(message),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise MessageError("메시지를 올바른 UTF-8 JSON으로 만들 수 없습니다") from exc
    if len(payload) > MAX_DATAGRAM_SIZE:
        raise MessageError("메시지가 UDP 데이터그램 하나에 담기에는 너무 큽니다")
    return payload


def _reject_json_constant(value: str) -> None:
    # Python의 JSON parser는 기본적으로 NaN/Infinity를 허용하지만,
    # 이 값들은 표준 JSON 값이 아니므로 wire 입력에서는 거부한다.
    raise ValueError(f"유한하지 않은 JSON 숫자: {value}")


def decode_message(payload: bytes | bytearray | memoryview) -> dict[str, Any]:
    """UDP payload를 UTF-8 JSON 객체로 해석한다.

    여기서는 JSON 형식과 최상위 객체 여부만 확인한다. 메시지 종류별 필드와
    값 검증은 이후 ``parse_advertisement()``, ``parse_ack()``,
    ``parse_detail()``이 담당한다.
    """

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise MessageError("payload는 bytes 계열 값이어야 합니다")
    raw_payload = bytes(payload)
    if not raw_payload or len(raw_payload) > MAX_DATAGRAM_SIZE:
        raise MessageError("payload 크기가 올바르지 않습니다")
    try:
        message = json.loads(
            raw_payload.decode("utf-8"), parse_constant=_reject_json_constant
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise MessageError("payload가 올바른 UTF-8 JSON이 아닙니다") from exc
    if not isinstance(message, dict):
        raise MessageError("메시지의 최상위 값은 JSON 객체여야 합니다")
    return message
