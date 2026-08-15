from __future__ import annotations

import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rtsp_bootstrap import (  # noqa: E402
    MessageError,
    MessageType,
    decode_message,
    encode_message,
    make_message,
    validate_message,
)


class ProtocolTests(unittest.TestCase):
    def test_utf8_json_round_trip(self) -> None:
        message = make_message(
            MessageType.DETAIL,
            device_id="카메라-01",
            message_id="detail-1",
            ip="192.168.0.10",
            rtsp_port=8554,
            rtsp_path="/stream",
            in_reply_to="advertise-1",
            details={"모델": "테스트"},
        )

        payload = encode_message(message)

        self.assertIn("카메라".encode(), payload)
        self.assertEqual(decode_message(payload), message)

    def test_ack_requires_correlation_id(self) -> None:
        with self.assertRaises(MessageError):
            make_message(
                MessageType.ACK,
                device_id="camera-1",
                ip="192.168.0.10",
                rtsp_port=8554,
                rtsp_path="/stream",
            )

    def test_invalid_wire_inputs_raise_one_public_error(self) -> None:
        valid = make_message(
            MessageType.ADVERTISE,
            device_id="camera-1",
            ip="192.168.0.10",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        invalid_payloads = [
            b"\xff",
            b"{broken",
            b"[]",
            b"NaN",
            encode_message(valid).replace(b'"1.0"', b'"9.0"', 1),
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(MessageError):
                decode_message(payload)

    def test_endpoint_and_type_validation(self) -> None:
        base = make_message(
            MessageType.ADVERTISE,
            device_id="camera-1",
            ip="192.168.0.10",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        invalid_changes = [
            {"message_type": "UNKNOWN"},
            {"device_id": ""},
            {"ip": "::1"},
            {"ip": "999.0.0.1"},
            {"rtsp_port": True},
            {"rtsp_port": 0},
            {"rtsp_port": 65_536},
            {"rtsp_path": "stream"},
            {"rtsp_path": "/bad\r\npath"},
        ]
        for change in invalid_changes:
            candidate = {**base, **change}
            with self.subTest(change=change), self.assertRaises(MessageError):
                validate_message(candidate)

    def test_non_json_detail_value_is_rejected(self) -> None:
        with self.assertRaises(MessageError):
            make_message(
                MessageType.DETAIL,
                device_id="camera-1",
                ip="192.168.0.10",
                rtsp_port=8554,
                rtsp_path="/stream",
                in_reply_to="advertise-1",
                details={"temperature": math.nan},
            )

    def test_lone_unicode_surrogate_is_rejected(self) -> None:
        payload = (
            b'{"protocol_version":"1.0","message_type":"ADVERTISE",'
            b'"device_id":"camera-1","message_id":"message-1",'
            b'"ip":"127.0.0.1","rtsp_port":8554,'
            b'"rtsp_path":"/\\ud800"}'
        )
        with self.assertRaises(MessageError):
            decode_message(payload)


if __name__ == "__main__":
    unittest.main()
