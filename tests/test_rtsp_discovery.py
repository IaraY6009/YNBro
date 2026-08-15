import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from rtsp_discovery import RtspDiscoveryResponder, discover_rtsp_devices  # noqa: E402
from rtsp_discovery.protocol import (  # noqa: E402
    make_request,
    make_response,
    parse_request,
    parse_response,
)


class RtspDiscoveryTests(unittest.TestCase):
    def test_packet_number_advances_across_request_and_response(self) -> None:
        request = parse_request(make_request(2))
        response = parse_response(
            make_response(
                "127.0.0.1",
                8554,
                "00:11:22:33:44:55",
                request["packet_number"] + 1,
            )
        )

        self.assertEqual(response["packet_number"], 3)

    def test_udp_responder_returns_mac_port_and_next_packet_number(self) -> None:
        responder = RtspDiscoveryResponder(
            rtsp_port=8554,
            discovery_port=37120,
            advertised_ip="127.0.0.1",
            mac="00:11:22:33:44:55",
        )
        thread = threading.Thread(target=responder.serve_forever, daemon=True)
        thread.start()

        try:
            time.sleep(0.1)
            devices = discover_rtsp_devices(
                discovery_port=37120,
                timeout=1.0,
                broadcast_address="127.0.0.1",
                packet_number=2,
            )
        finally:
            responder.stop()
            thread.join(timeout=1.0)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].ip, "127.0.0.1")
        self.assertEqual(devices[0].port, 8554)
        self.assertEqual(devices[0].mac, "00:11:22:33:44:55")
        self.assertEqual(devices[0].packet_number, 3)


if __name__ == "__main__":
    unittest.main()
