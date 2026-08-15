from __future__ import annotations

import pathlib
import queue
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rtsp_bootstrap import BootstrapReceiver, BootstrapSender  # noqa: E402

from tests.support import FakeRtspServer  # noqa: E402


class EndToEndTests(unittest.TestCase):
    def test_advertise_rtsp_detail_ack_flow_and_multiple_devices(self) -> None:
        server = FakeRtspServer()
        self.addCleanup(server.close)
        discovered: queue.Queue[dict[str, object]] = queue.Queue()
        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_timeout=1.0,
            on_device=discovered.put,
        ).start()
        self.addCleanup(receiver.stop)
        assert receiver.local_address is not None

        detail_acks: queue.Queue[dict[str, object]] = queue.Queue()
        senders = [
            BootstrapSender(
                device_id=f"camera-{number}",
                ip="127.0.0.1",
                rtsp_port=server.port,
                rtsp_path=f"/stream-{number}",
                details={"model": "demo", "number": number},
                discovery_port=receiver.local_address[1],
                broadcast_address="127.0.0.1",
                advertise_interval=0.2,
                on_detail_ack=detail_acks.put,
            ).start()
            for number in (1, 2)
        ]
        for sender in senders:
            self.addCleanup(sender.stop)

        discovered_devices: set[object] = set()
        while len(discovered_devices) < 2:
            discovered_devices.add(discovered.get(timeout=3.0)["device_id"])
        ack_records = [detail_acks.get(timeout=3.0), detail_acks.get(timeout=3.0)]

        self.assertEqual(discovered_devices, {"camera-1", "camera-2"})
        self.assertEqual(len(ack_records), 2)
        states = receiver.get_devices()
        self.assertEqual(set(states), {"camera-1", "camera-2"})
        for number in (1, 2):
            state = states[f"camera-{number}"]
            self.assertTrue(state["rtsp_connected"])
            self.assertEqual(state["details"], {"model": "demo", "number": number})
            self.assertEqual(
                state["rtsp_uri"],
                f"rtsp://127.0.0.1:{server.port}/stream-{number}",
            )
        for record in ack_records:
            self.assertEqual(record["ack"]["ack_for"], record["message_id"])

    def test_detail_ack_does_not_claim_rtsp_success(self) -> None:
        detail_acks: queue.Queue[dict[str, object]] = queue.Queue()
        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=lambda *_args: False,
        ).start()
        self.addCleanup(receiver.stop)
        assert receiver.local_address is not None
        sender = BootstrapSender(
            device_id="offline-camera",
            ip="127.0.0.1",
            rtsp_port=9,
            rtsp_path="/stream",
            details={"model": "offline-demo"},
            discovery_port=receiver.local_address[1],
            broadcast_address="127.0.0.1",
            advertise_interval=10.0,
            on_detail_ack=detail_acks.put,
        ).start()
        self.addCleanup(sender.stop)

        ack = detail_acks.get(timeout=2.0)

        self.assertEqual(ack["ack"]["ack_for"], ack["message_id"])
        state = receiver.get_devices()["offline-camera"]
        self.assertFalse(state["rtsp_connected"])
        self.assertEqual(state["details"], {"model": "offline-demo"})
        self.assertIsNone(sender.wait_for_ack("unknown", timeout=0.01))

    def test_discover_returns_only_devices_seen_during_that_call(self) -> None:
        server = FakeRtspServer()
        self.addCleanup(server.close)
        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_timeout=1.0,
        ).start()
        self.addCleanup(receiver.stop)
        assert receiver.local_address is not None
        sender = BootstrapSender(
            device_id="window-camera",
            ip="127.0.0.1",
            rtsp_port=server.port,
            rtsp_path="/stream",
            discovery_port=receiver.local_address[1],
            broadcast_address="127.0.0.1",
            advertise_interval=0.03,
        ).start()
        self.addCleanup(sender.stop)

        first_window = receiver.discover(0.3)
        receiver.stop()
        sender.stop()
        second_window = receiver.discover(0.1)

        self.assertEqual([item["device_id"] for item in first_window], ["window-camera"])
        self.assertEqual(second_window, [])


if __name__ == "__main__":
    unittest.main()
