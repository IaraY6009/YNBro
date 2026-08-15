from __future__ import annotations

import pathlib
import queue
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from rtsp_bootstrap import (  # noqa: E402
    BootstrapReceiver,
    MessageType,
    decode_message,
    encode_message,
    make_message,
)

from tests.support import udp_client  # noqa: E402


class ReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.callbacks: queue.Queue[dict[str, object]] = queue.Queue()
        self.probe_count = 0
        self.probe_lock = threading.Lock()

        def successful_probe(_ip: str, _port: int, _path: str, _timeout: float) -> bool:
            with self.probe_lock:
                self.probe_count += 1
            return True

        self.receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=successful_probe,
            on_device=self.callbacks.put,
        ).start()
        self.addCleanup(self.receiver.stop)
        self.client = udp_client()
        self.addCleanup(self.client.close)
        assert self.receiver.local_address is not None
        self.target = self.receiver.local_address

    def _send(self, message: dict[str, object]) -> dict[str, object]:
        self.client.sendto(encode_message(message), self.target)
        payload, _peer = self.client.recvfrom(65_535)
        return decode_message(payload)

    def test_duplicate_device_and_message_are_processed_once_but_reacked(self) -> None:
        advertise = make_message(
            MessageType.ADVERTISE,
            message_id="advertise-1",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )

        first_ack = self._send(advertise)
        first_device = self.callbacks.get(timeout=1.0)
        second_ack = self._send(advertise)

        self.assertEqual(first_ack["ack_for"], "advertise-1")
        self.assertEqual(second_ack["ack_for"], "advertise-1")
        with self.assertRaises(queue.Empty):
            self.callbacks.get(timeout=0.1)
        self.assertEqual(self.probe_count, 1)
        self.assertEqual(first_device["device_id"], "camera-1")
        self.assertEqual(list(self.receiver.get_devices()), ["camera-1"])

    def test_detail_updates_state_and_duplicate_is_reacked(self) -> None:
        advertise = make_message(
            MessageType.ADVERTISE,
            message_id="advertise-1",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        self._send(advertise)
        self.callbacks.get(timeout=1.0)
        detail = make_message(
            MessageType.DETAIL,
            message_id="detail-1",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
            in_reply_to="advertise-1",
            details={"model": "demo", "location": "lab"},
        )

        self.assertEqual(self._send(detail)["ack_for"], "detail-1")
        self.assertEqual(self._send(detail)["ack_for"], "detail-1")

        state = self.receiver.get_devices()["camera-1"]
        self.assertEqual(state["details"], {"model": "demo", "location": "lab"})
        self.assertTrue(state["rtsp_connected"])
        update = self.callbacks.get(timeout=1.0)
        self.assertEqual(update["details"], {"model": "demo", "location": "lab"})
        with self.assertRaises(queue.Empty):
            self.callbacks.get(timeout=0.1)

    def test_malformed_packet_and_probe_exception_do_not_stop_listener(self) -> None:
        self.client.sendto(b"not-json", self.target)

        def selective_probe(_ip: str, _port: int, path: str, _timeout: float) -> bool:
            if path == "/timeout":
                raise TimeoutError
            return True

        self.receiver._rtsp_probe = selective_probe
        failed = make_message(
            MessageType.ADVERTISE,
            device_id="failed-camera",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/timeout",
        )
        failed_ack = self._send(failed)
        good = make_message(
            MessageType.ADVERTISE,
            device_id="good-camera",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        ack = self._send(good)
        device = self.callbacks.get(timeout=1.0)

        self.assertEqual(failed_ack["device_id"], "failed-camera")
        self.assertEqual(ack["device_id"], "good-camera")
        self.assertEqual(device["device_id"], "good-camera")
        states = self.receiver.get_devices()
        self.assertFalse(states["failed-camera"]["rtsp_connected"])
        self.assertTrue(states["good-camera"]["rtsp_connected"])

    def test_stale_detail_cannot_roll_back_latest_endpoint(self) -> None:
        old_advertisement = make_message(
            MessageType.ADVERTISE,
            message_id="advertise-old",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8001,
            rtsp_path="/old",
        )
        self._send(old_advertisement)
        self.callbacks.get(timeout=1.0)
        new_advertisement = make_message(
            MessageType.ADVERTISE,
            message_id="advertise-new",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8002,
            rtsp_path="/new",
        )
        self._send(new_advertisement)
        self.callbacks.get(timeout=1.0)
        stale_detail = make_message(
            MessageType.DETAIL,
            message_id="detail-old",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8001,
            rtsp_path="/old",
            in_reply_to="advertise-old",
            details={"stale": True},
        )

        self.client.settimeout(0.1)
        self.client.sendto(encode_message(stale_detail), self.target)
        with self.assertRaises(socket.timeout):
            self.client.recvfrom(65_535)

        state = self.receiver.get_devices()["camera-1"]
        self.assertEqual((state["rtsp_port"], state["rtsp_path"]), (8002, "/new"))
        self.assertEqual(state["details"], {})

    def test_callback_can_stop_receiver_without_deadlock(self) -> None:
        callback_returned = threading.Event()
        holder: dict[str, BootstrapReceiver] = {}

        def stop_from_callback(_device: dict[str, object]) -> None:
            holder["receiver"].stop()
            callback_returned.set()

        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=lambda *_args: True,
            on_device=stop_from_callback,
        )
        holder["receiver"] = receiver
        receiver.start()
        self.addCleanup(receiver.stop)
        client = udp_client()
        self.addCleanup(client.close)
        assert receiver.local_address is not None
        advertisement = make_message(
            MessageType.ADVERTISE,
            device_id="self-stopping-camera",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )

        client.sendto(encode_message(advertisement), receiver.local_address)
        client.recvfrom(65_535)
        self.assertTrue(callback_returned.wait(1.0))
        receiver.stop(timeout=1.0)
        self.assertFalse(receiver.is_running)

    def test_advertisement_ack_does_not_wait_for_rtsp_probe(self) -> None:
        release_probe = threading.Event()

        def blocked_probe(*_args: object) -> bool:
            release_probe.wait(1.0)
            return False

        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=blocked_probe,
        ).start()
        self.addCleanup(receiver.stop)
        self.addCleanup(release_probe.set)
        client = udp_client()
        self.addCleanup(client.close)
        assert receiver.local_address is not None
        advertisement = make_message(
            MessageType.ADVERTISE,
            message_id="slow-probe-advertisement",
            device_id="slow-camera",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )

        client.sendto(encode_message(advertisement), receiver.local_address)
        payload, _peer = client.recvfrom(65_535)

        self.assertEqual(
            decode_message(payload)["ack_for"], "slow-probe-advertisement"
        )
        release_probe.set()

    def test_probe_failure_then_recovery_emits_new_success(self) -> None:
        outcomes: queue.Queue[bool] = queue.Queue()
        for outcome in (True, False, True):
            outcomes.put(outcome)
        callbacks: queue.Queue[dict[str, object]] = queue.Queue()
        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            probe_success_ttl=0.001,
            rtsp_probe=lambda *_args: outcomes.get_nowait(),
            on_device=callbacks.put,
        ).start()
        self.addCleanup(receiver.stop)
        client = udp_client()
        self.addCleanup(client.close)
        assert receiver.local_address is not None

        def advertise(message_id: str) -> None:
            message = make_message(
                MessageType.ADVERTISE,
                message_id=message_id,
                device_id="recovering-camera",
                ip="127.0.0.1",
                rtsp_port=8554,
                rtsp_path="/stream",
            )
            client.sendto(encode_message(message), receiver.local_address)
            client.recvfrom(65_535)

        advertise("advertise-success-1")
        self.assertTrue(callbacks.get(timeout=1.0)["rtsp_connected"])
        threading.Event().wait(0.01)
        advertise("advertise-failure")

        deadline = time.monotonic() + 1.0
        while receiver.get_devices()["recovering-camera"]["rtsp_connected"]:
            if time.monotonic() >= deadline:
                self.fail("failed probe result was not applied")
            threading.Event().wait(0.01)

        advertise("advertise-success-2")
        recovered = callbacks.get(timeout=1.0)
        self.assertTrue(recovered["rtsp_connected"])
        self.assertEqual(recovered["device_id"], "recovering-camera")

    def test_probe_can_request_receiver_stop(self) -> None:
        probe_returned = threading.Event()
        running_after_stop: list[bool] = []
        holder: dict[str, BootstrapReceiver] = {}

        def self_stopping_probe(*_args: object) -> bool:
            holder["receiver"].stop(timeout=1.0)
            running_after_stop.append(holder["receiver"].is_running)
            probe_returned.set()
            return True

        receiver = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_probe=self_stopping_probe,
        )
        holder["receiver"] = receiver
        receiver.start()
        self.addCleanup(receiver.stop)
        client = udp_client()
        self.addCleanup(client.close)
        assert receiver.local_address is not None
        advertisement = make_message(
            MessageType.ADVERTISE,
            device_id="probe-stopping-camera",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )

        client.sendto(encode_message(advertisement), receiver.local_address)
        client.recvfrom(65_535)

        self.assertTrue(probe_returned.wait(2.0))
        self.assertEqual(running_after_stop, [False])

    def test_detail_for_previous_same_endpoint_advertisement_is_accepted(self) -> None:
        first = make_message(
            MessageType.ADVERTISE,
            message_id="same-endpoint-1",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        second = make_message(
            MessageType.ADVERTISE,
            message_id="same-endpoint-2",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
        )
        self._send(first)
        self.callbacks.get(timeout=1.0)
        self._send(second)
        delayed_detail = make_message(
            MessageType.DETAIL,
            message_id="delayed-detail",
            device_id="camera-1",
            ip="127.0.0.1",
            rtsp_port=8554,
            rtsp_path="/stream",
            in_reply_to="same-endpoint-1",
            details={"reordered": True},
        )

        ack = self._send(delayed_detail)

        self.assertEqual(ack["ack_for"], "delayed-detail")
        self.assertEqual(
            self.receiver.get_devices()["camera-1"]["details"],
            {"reordered": True},
        )

    def test_discover_timeout_returns_without_an_exception(self) -> None:
        other = BootstrapReceiver(
            bind_host="127.0.0.1",
            discovery_port=0,
            rtsp_timeout=0.1,
        )
        self.addCleanup(other.stop)
        self.assertEqual(other.discover(0.05), [])


if __name__ == "__main__":
    unittest.main()
