from __future__ import annotations

import math
import unittest

from ynb._protocol import (
    MessageError,
    decode_message,
    encode_message,
    make_ack,
    make_advertisement,
    make_detail,
    parse_advertisement,
    parse_ack,
    parse_detail,
    validate_port,
    validate_rtsp_path,
    validate_timeout,
)


DEVICE_ID = "DC:A6:32:12:34:56"


class ProtocolTests(unittest.TestCase):
    def test_wire_messages_use_the_exact_0_0_1_fields(self) -> None:
        self.assertEqual(
            make_advertisement(DEVICE_ID),
            {"message_type": "ADVERTISE", "device_id": DEVICE_ID},
        )
        self.assertEqual(
            make_ack(DEVICE_ID, "DETAIL"),
            {
                "message_type": "ACK",
                "device_id": DEVICE_ID,
                "ack_for": "DETAIL",
            },
        )
        self.assertEqual(
            make_detail(DEVICE_ID, "127.0.0.1", 8554, "/stream"),
            {
                "message_type": "DETAIL",
                "device_id": DEVICE_ID,
                "ip": "127.0.0.1",
                "rtsp_port": 8554,
                "rtsp_path": "/stream",
            },
        )

    def test_validation_rejects_invalid_endpoint_before_network_use(self) -> None:
        for args in (
            ("not-a-mac", "127.0.0.1", 8554, "/stream"),
            (DEVICE_ID, "999.0.0.1", 8554, "/stream"),
            (DEVICE_ID, "127.0.0.1", True, "/stream"),
            (DEVICE_ID, "127.0.0.1", 8554, "stream"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                make_detail(*args)

    def test_malformed_and_extended_messages_are_rejected(self) -> None:
        with self.assertRaises(MessageError):
            decode_message(b"not-json")
        with self.assertRaises(MessageError):
            parse_advertisement(
                {
                    "message_type": "ADVERTISE",
                    "device_id": DEVICE_ID,
                    "ip": "127.0.0.1",
                }
            )
        with self.assertRaises(MessageError):
            parse_ack(
                {
                    "message_type": "ACK",
                    "device_id": DEVICE_ID,
                    "ack_for": [],
                }
            )
        with self.assertRaises(MessageError):
            parse_detail(
                {
                    "message_type": "DETAIL",
                    "device_id": DEVICE_ID,
                    "ip": "127.0.0.1",
                    "rtsp_port": 8554,
                    "rtsp_path": "/stream",
                    "message_id": "outside-0.0.1",
                }
            )

    def test_utf8_json_round_trip(self) -> None:
        message = make_detail(DEVICE_ID, "127.0.0.1", 8554, "/카메라")
        self.assertEqual(decode_message(encode_message(message)), message)

    def test_port_and_timeout_boundaries(self) -> None:
        self.assertEqual(validate_port(1), 1)
        self.assertEqual(validate_port(65_535), 65_535)
        self.assertEqual(validate_timeout(0), 0.0)

        for value in (0, -1, 65_536, True, 1.5, "8554"):
            with self.subTest(port=value), self.assertRaises(ValueError):
                validate_port(value)

        for value in (-1, math.nan, math.inf, -math.inf, True, "1"):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                validate_timeout(value)

    def test_invalid_wire_json_and_unsafe_paths_are_rejected(self) -> None:
        for payload in (
            b"",
            b"\xff",
            b"[]",
            b'"string"',
            b"null",
            b'{"value":NaN}',
        ):
            with self.subTest(payload=payload), self.assertRaises(MessageError):
                decode_message(payload)

        for path in ("", "stream", "/line\rbreak", "/line\nbreak", "/\x7f"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_rtsp_path(path)


if __name__ == "__main__":
    unittest.main()
