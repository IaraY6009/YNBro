from __future__ import annotations

import pathlib
import socket
import sys
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rtsp_bootstrap import (  # noqa: E402
    BootstrapReceiver,
    BootstrapSender,
    MessageError,
)


class SenderAndLifecycleTests(unittest.TestCase):
    def test_invalid_detail_configuration_fails_before_start(self) -> None:
        with self.assertRaises(MessageError):
            BootstrapSender(
                device_id="camera-1",
                ip="127.0.0.1",
                rtsp_port=8554,
                rtsp_path="/stream",
                details={"invalid": object()},
            )

    def test_waiter_is_released_when_sender_stops(self) -> None:
        sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sink.bind(("127.0.0.1", 0))
        self.addCleanup(sink.close)
        sender = BootstrapSender(
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
            discovery_port=int(sink.getsockname()[1]),
            broadcast_address="127.0.0.1",
        ).start()
        self.addCleanup(sender.stop)
        result: list[object] = []
        waiter = threading.Thread(
            target=lambda: result.append(sender.wait_for_ack("never")), daemon=True
        )
        waiter.start()

        sender.stop()
        waiter.join(1.0)

        self.assertFalse(waiter.is_alive())
        self.assertEqual(result, [None])

    def test_stop_without_wait_then_restart(self) -> None:
        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=lambda *_args: False,
        ).start()
        self.addCleanup(receiver.stop)
        receiver.stop(wait=False)
        receiver.start(startup_timeout=2.0)
        self.assertTrue(receiver.is_running)

        assert receiver.local_address is not None
        sender = BootstrapSender(
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
            discovery_port=receiver.local_address[1],
            broadcast_address="127.0.0.1",
        ).start()
        self.addCleanup(sender.stop)
        sender.stop(wait=False)
        sender.start(startup_timeout=2.0)
        self.assertTrue(sender.is_running)

    def test_old_waiter_is_cancelled_across_immediate_restart(self) -> None:
        sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sink.bind(("127.0.0.1", 0))
        self.addCleanup(sink.close)
        sender = BootstrapSender(
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
            discovery_port=int(sink.getsockname()[1]),
            broadcast_address="127.0.0.1",
        ).start()
        self.addCleanup(sender.stop)
        result: list[object] = []
        waiter = threading.Thread(
            target=lambda: result.append(sender.wait_for_ack("old-run")), daemon=True
        )
        waiter.start()

        sender.stop(wait=False)
        sender.start(startup_timeout=2.0)
        waiter.join(1.0)

        self.assertFalse(waiter.is_alive())
        self.assertEqual(result, [None])


if __name__ == "__main__":
    unittest.main()
