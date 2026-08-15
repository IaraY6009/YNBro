from __future__ import annotations

import pathlib
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rtsp_bootstrap import build_rtsp_uri, probe_rtsp  # noqa: E402

from tests.support import FakeRtspServer  # noqa: E402


class RtspProbeTests(unittest.TestCase):
    def test_options_request_and_rtsp_2_success(self) -> None:
        server = FakeRtspServer()
        self.addCleanup(server.close)

        self.assertTrue(probe_rtsp("127.0.0.1", server.port, "/stream", 1.0))

        request = server.requests.get(timeout=1.0)
        expected_line = (
            f"OPTIONS rtsp://127.0.0.1:{server.port}/stream RTSP/2.0\r\n"
        ).encode()
        self.assertTrue(request.startswith(expected_line))
        self.assertIn(b"CSeq: 1\r\n", request)

    def test_non_2xx_or_wrong_protocol_is_not_success(self) -> None:
        for response in (
            b"RTSP/2.0 404 Not Found\r\nCSeq: 1\r\n\r\n",
            b"RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n",
            b"RTSP/2.0 200 OK\r\nCSeq: 999\r\n\r\n",
        ):
            with self.subTest(response=response):
                server = FakeRtspServer(response)
                try:
                    self.assertFalse(
                        probe_rtsp("127.0.0.1", server.port, "/stream", 1.0)
                    )
                finally:
                    server.close()

    def test_socket_timeout_is_a_normal_false_result(self) -> None:
        with mock.patch(
            "rtsp_bootstrap.rtsp.socket.create_connection",
            side_effect=socket.timeout,
        ):
            self.assertFalse(probe_rtsp("127.0.0.1", 8554, "/stream", 0.1))

    def test_uri_percent_encodes_non_ascii_path(self) -> None:
        self.assertEqual(
            build_rtsp_uri("192.168.0.10", 8554, "/영상"),
            "rtsp://192.168.0.10:8554/%EC%98%81%EC%83%81",
        )


if __name__ == "__main__":
    unittest.main()
