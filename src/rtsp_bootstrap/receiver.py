"""UDP receiver and device registry for RTSP bootstrap discovery."""

from __future__ import annotations

import copy
import logging
import math
import queue
import socket
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .protocol import (
    MAX_DATAGRAM_SIZE,
    MessageError,
    MessageType,
    decode_message,
    encode_message,
    make_message,
)
from .rtsp import build_rtsp_uri, probe_rtsp

LOGGER = logging.getLogger(__name__)

DeviceCallback = Callable[[dict[str, Any]], None]
RtspProbe = Callable[[str, int, str, float], bool]


class BootstrapReceiver:
    """Discover devices, verify RTSP/2.0, and retain their latest state."""

    def __init__(
        self,
        *,
        bind_host: str = "0.0.0.0",
        discovery_port: int = 37_020,
        rtsp_timeout: float = 2.0,
        on_device: DeviceCallback | None = None,
        rtsp_probe: RtspProbe | None = None,
        max_probe_workers: int = 4,
        max_pending_probes: int = 128,
        probe_success_ttl: float = 10.0,
        dedupe_capacity: int = 4_096,
    ) -> None:
        if not isinstance(discovery_port, int) or isinstance(discovery_port, bool):
            raise ValueError("discovery_port must be an integer")
        if not 0 <= discovery_port <= 65_535:
            raise ValueError("discovery_port must be from 0 to 65535")
        if (
            isinstance(rtsp_timeout, bool)
            or not isinstance(rtsp_timeout, (int, float))
            or not math.isfinite(rtsp_timeout)
            or rtsp_timeout <= 0
        ):
            raise ValueError("rtsp_timeout must be greater than zero")
        if (
            isinstance(max_probe_workers, bool)
            or not isinstance(max_probe_workers, int)
            or max_probe_workers < 1
        ):
            raise ValueError("max_probe_workers must be at least one")
        if (
            isinstance(max_pending_probes, bool)
            or not isinstance(max_pending_probes, int)
            or max_pending_probes < 1
        ):
            raise ValueError("max_pending_probes must be at least one")
        if (
            isinstance(probe_success_ttl, bool)
            or not isinstance(probe_success_ttl, (int, float))
            or not math.isfinite(probe_success_ttl)
            or probe_success_ttl <= 0
        ):
            raise ValueError("probe_success_ttl must be greater than zero")
        if (
            isinstance(dedupe_capacity, bool)
            or not isinstance(dedupe_capacity, int)
            or dedupe_capacity < 1
        ):
            raise ValueError("dedupe_capacity must be at least one")

        self.bind_host = bind_host
        self.discovery_port = discovery_port
        self.rtsp_timeout = float(rtsp_timeout)
        self.on_device = on_device
        self._rtsp_probe = rtsp_probe or probe_rtsp
        self._max_probe_workers = max_probe_workers
        self._probe_slots = threading.BoundedSemaphore(max_pending_probes)
        self._probe_success_ttl = float(probe_success_ttl)
        self._dedupe_capacity = dedupe_capacity

        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._devices: dict[str, dict[str, Any]] = {}
        self._seen_messages: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._inflight: dict[
            str, tuple[int, str, tuple[str, int, str]]
        ] = {}
        self._reported_endpoints: dict[str, tuple[str, int, str]] = {}
        self._latest_advertisements: dict[
            str, tuple[str, tuple[str, int, str], tuple[str, int], int]
        ] = {}
        self._advertisement_contexts: OrderedDict[
            tuple[str, str], tuple[tuple[str, int, str], tuple[str, int], int]
        ] = OrderedDict()
        self._device_context_epoch: dict[str, int] = {}
        self._message_sequence = 0
        self._device_seen_sequence: dict[str, int] = {}
        self._last_probe_success: dict[str, float] = {}
        self._probe_results: queue.SimpleQueue[
            tuple[int, str, str, tuple[str, int, str], bool]
        ] = queue.SimpleQueue()
        self._probe_worker_context = threading.local()

        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._local_address: tuple[str, int] | None = None
        self._start_error: BaseException | None = None
        self._run_generation = 0
        self._stop_from_probe = threading.Event()

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Return the actual UDP bind address once the receiver is running."""

        with self._lifecycle_lock:
            return self._local_address

    @property
    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._running

    def start(self, *, startup_timeout: float = 3.0) -> "BootstrapReceiver":
        """Run the receiver in a background thread and wait until bind completes."""

        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")
        deadline = time.monotonic() + startup_timeout

        while True:
            stopping_thread: threading.Thread | None = None
            with self._lifecycle_lock:
                existing_thread = self._thread
                if existing_thread is not None and existing_thread.is_alive():
                    if self._stop_event.is_set():
                        stopping_thread = existing_thread
                    else:
                        thread = existing_thread
                        break
                elif self._running:
                    return self
                else:
                    self._stop_event.clear()
                    self._stop_from_probe.clear()
                    self._ready_event.clear()
                    self._start_error = None
                    self._run_generation += 1
                    with self._state_lock:
                        self._seen_messages.clear()
                        self._latest_advertisements.clear()
                        self._advertisement_contexts.clear()
                    thread = threading.Thread(
                        target=self._background_main,
                        name="rtsp-bootstrap-receiver",
                        daemon=True,
                    )
                    self._thread = thread
                    thread.start()
                    break
            if stopping_thread is threading.current_thread():
                raise RuntimeError("cannot restart receiver while it is stopping")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("previous receiver run did not stop")
            stopping_thread.join(remaining)
            if stopping_thread.is_alive():
                raise TimeoutError("previous receiver run did not stop")

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._ready_event.wait(remaining):
            self.stop()
            raise TimeoutError("receiver did not start before the timeout")
        if self._start_error is not None:
            error = self._start_error
            self.stop()
            raise RuntimeError("receiver could not bind its UDP socket") from error
        return self

    def _background_main(self) -> None:
        try:
            self._serve(prepared=True)
        except BaseException:
            if self._start_error is None:
                LOGGER.exception("receiver background thread stopped unexpectedly")

    def serve_forever(self) -> None:
        """Receive datagrams until :meth:`stop` is called."""

        self._serve(prepared=False)

    def _serve(self, *, prepared: bool) -> None:
        current_thread = threading.current_thread()
        with self._lifecycle_lock:
            if self._running:
                raise RuntimeError("receiver is already running")
            self._running = True
            if not prepared:
                self._stop_event.clear()
                self._stop_from_probe.clear()
                self._ready_event.clear()
                self._start_error = None
                self._run_generation += 1
                with self._state_lock:
                    self._seen_messages.clear()
                    self._latest_advertisements.clear()
                    self._advertisement_contexts.clear()
                self._thread = current_thread
            self._local_address = None

        udp_socket: socket.socket | None = None
        executor: ThreadPoolExecutor | None = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.bind((self.bind_host, self.discovery_port))
            udp_socket.settimeout(0.2)
            executor = ThreadPoolExecutor(
                max_workers=self._max_probe_workers,
                thread_name_prefix="rtsp-bootstrap-probe",
            )
            with self._lifecycle_lock:
                self._socket = udp_socket
                self._executor = executor
                bound_host, bound_port = udp_socket.getsockname()[:2]
                self._local_address = (str(bound_host), int(bound_port))
            self._ready_event.set()

            while not self._stop_event.is_set():
                try:
                    payload, peer = udp_socket.recvfrom(MAX_DATAGRAM_SIZE + 1)
                except socket.timeout:
                    pass
                except OSError:
                    if self._stop_event.is_set():
                        break
                    LOGGER.debug("transient UDP receive failure", exc_info=True)
                else:
                    try:
                        self._handle_datagram(
                            payload, (str(peer[0]), int(peer[1]))
                        )
                    except Exception:
                        LOGGER.exception("ignored bootstrap datagram after handler error")
                self._drain_probe_results()
        except BaseException as exc:
            if not self._ready_event.is_set():
                self._start_error = exc
                self._ready_event.set()
            raise
        finally:
            self._stop_event.set()
            if udp_socket is not None:
                try:
                    udp_socket.close()
                except OSError:
                    pass
            if executor is not None:
                executor.shutdown(
                    wait=not self._stop_from_probe.is_set(),
                    cancel_futures=True,
                )
            with self._state_lock:
                self._inflight.clear()
            while True:
                try:
                    self._probe_results.get_nowait()
                except queue.Empty:
                    break
            with self._lifecycle_lock:
                self._socket = None
                self._executor = None
                self._running = False
                if self._thread is current_thread:
                    self._thread = None
            self._ready_event.set()

    def stop(self, *, wait: bool = True, timeout: float | None = None) -> None:
        """Request an idempotent shutdown."""

        self._stop_event.set()
        with self._lifecycle_lock:
            thread = self._thread
        called_from_probe = bool(getattr(self._probe_worker_context, "active", False))
        if called_from_probe:
            self._stop_from_probe.set()
        if (
            wait
            and thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(timeout)

    close = stop

    def discover(self, timeout: float = 5.0) -> list[dict[str, Any]]:
        """Listen for ``timeout`` seconds and return RTSP-reachable devices."""

        if timeout < 0:
            raise ValueError("timeout must not be negative")
        with self._state_lock:
            started_at_sequence = self._message_sequence
        started_here = not self.is_running
        if started_here:
            self.start()
        self._stop_event.wait(timeout)
        if started_here:
            self.stop(wait=True, timeout=self.rtsp_timeout + 1.0)
        with self._state_lock:
            return [
                copy.deepcopy(device)
                for device_id, device in self._devices.items()
                if device["rtsp_connected"]
                and self._device_seen_sequence.get(device_id, 0)
                > started_at_sequence
            ]

    def get_devices(self) -> dict[str, dict[str, Any]]:
        """Return a deep-copy snapshot keyed by ``device_id``."""

        with self._state_lock:
            return copy.deepcopy(self._devices)

    def _remember_message(self, message: dict[str, Any]) -> bool:
        key = (message["device_id"], message["message_id"])
        with self._state_lock:
            if key in self._seen_messages:
                self._seen_messages.move_to_end(key)
                return False
            self._seen_messages[key] = None
            while len(self._seen_messages) > self._dedupe_capacity:
                self._seen_messages.popitem(last=False)
            return True

    def _handle_datagram(self, payload: bytes, peer: tuple[str, int]) -> None:
        try:
            message = decode_message(payload)
        except (MessageError, RecursionError):
            LOGGER.debug("ignored malformed bootstrap datagram from %s:%s", *peer)
            return

        message_type = MessageType(message["message_type"])
        if message_type is MessageType.ADVERTISE:
            is_new = self._remember_message(message)
            _connected, needs_probe = self._register_advertisement(
                message, peer, is_new
            )
            # ACK confirms JSON information receipt only. It is deliberately
            # independent from RTSP reachability or playback success.
            self._send_ack(message, peer)
            if needs_probe:
                self._schedule_probe(message)
        elif message_type is MessageType.DETAIL:
            if not self._detail_matches_latest_advertisement(message, peer):
                return
            is_new = self._remember_message(message)
            accepted, callback_payload = self._register_detail(
                message, peer, is_new
            )
            if accepted:
                # Re-ACK accepted duplicates so a lost ACK does not stall the sender.
                self._send_ack(message, peer)
            if callback_payload is not None:
                self._invoke_callback(callback_payload)

    def _detail_matches_latest_advertisement(
        self, message: dict[str, Any], peer: tuple[str, int]
    ) -> bool:
        endpoint = (message["ip"], message["rtsp_port"], message["rtsp_path"])
        with self._state_lock:
            context = self._advertisement_contexts.get(
                (message["device_id"], message["in_reply_to"])
            )
            latest = self._latest_advertisements.get(message["device_id"])
            current = self._devices.get(message["device_id"])
            current_endpoint = (
                (current["ip"], current["rtsp_port"], current["rtsp_path"])
                if current is not None
                else None
            )
            return bool(
                context is not None
                and latest is not None
                and context == (endpoint, peer, latest[3])
                and latest[1:3] == (endpoint, peer)
                and current_endpoint == endpoint
            )

    def _register_advertisement(
        self,
        message: dict[str, Any],
        peer: tuple[str, int],
        is_new: bool,
    ) -> tuple[bool, bool]:
        endpoint = (message["ip"], message["rtsp_port"], message["rtsp_path"])
        now_wall = time.time()
        now_monotonic = time.monotonic()
        with self._state_lock:
            current = self._devices.get(message["device_id"])
            old_endpoint = None
            if current is not None:
                old_endpoint = (
                    current["ip"],
                    current["rtsp_port"],
                    current["rtsp_path"],
                )
            same_endpoint = old_endpoint == endpoint
            details = (
                copy.deepcopy(current.get("details", {}))
                if current and same_endpoint
                else {}
            )
            connected = bool(
                current and current["rtsp_connected"] and same_endpoint
            )

            if is_new or current is None:
                previous_context = self._latest_advertisements.get(
                    message["device_id"]
                )
                context_epoch = self._device_context_epoch.get(
                    message["device_id"], 0
                )
                if (
                    previous_context is None
                    or previous_context[1] != endpoint
                    or previous_context[2] != peer
                ):
                    context_epoch += 1
                    self._device_context_epoch[message["device_id"]] = context_epoch
                if not same_endpoint:
                    self._reported_endpoints.pop(message["device_id"], None)
                    self._last_probe_success.pop(message["device_id"], None)
                self._devices[message["device_id"]] = {
                    "protocol_version": message["protocol_version"],
                    "device_id": message["device_id"],
                    "message_id": message["message_id"],
                    "ip": message["ip"],
                    "rtsp_port": message["rtsp_port"],
                    "rtsp_path": message["rtsp_path"],
                    "rtsp_uri": build_rtsp_uri(*endpoint),
                    "details": details,
                    "rtsp_connected": connected,
                    "last_seen": now_wall,
                }
                self._latest_advertisements[message["device_id"]] = (
                    message["message_id"],
                    endpoint,
                    peer,
                    context_epoch,
                )
                context_key = (message["device_id"], message["message_id"])
                self._advertisement_contexts[context_key] = (
                    endpoint,
                    peer,
                    context_epoch,
                )
                self._advertisement_contexts.move_to_end(context_key)
                while len(self._advertisement_contexts) > self._dedupe_capacity:
                    self._advertisement_contexts.popitem(last=False)
                self._mark_device_seen(message["device_id"])
            else:
                latest = self._latest_advertisements.get(message["device_id"])
                if latest is not None and latest[0] == message["message_id"]:
                    current["last_seen"] = now_wall
                    self._mark_device_seen(message["device_id"])

            last_success = self._last_probe_success.get(message["device_id"], 0.0)
            probe_is_fresh = (
                connected and now_monotonic - last_success < self._probe_success_ttl
            )
            needs_probe = is_new and not probe_is_fresh
            return connected, needs_probe

    def _register_detail(
        self,
        message: dict[str, Any],
        peer: tuple[str, int],
        is_new: bool,
    ) -> tuple[bool, dict[str, Any] | None]:
        endpoint = (message["ip"], message["rtsp_port"], message["rtsp_path"])
        now_wall = time.time()
        with self._state_lock:
            current = self._devices.get(message["device_id"])
            if (
                current is None
                or not self._detail_matches_latest_advertisement(message, peer)
            ):
                return False, None
            if not is_new:
                current["last_seen"] = now_wall
                self._mark_device_seen(message["device_id"])
                return True, None

            details_changed = current["details"] != message["details"]
            current.update(
                {
                    "protocol_version": message["protocol_version"],
                    "message_id": message["message_id"],
                    "details": copy.deepcopy(message["details"]),
                    "last_seen": now_wall,
                }
            )
            self._mark_device_seen(message["device_id"])
            callback_payload = (
                copy.deepcopy(current)
                if details_changed and current["rtsp_connected"]
                else None
            )
            return True, callback_payload

    def _mark_device_seen(self, device_id: str) -> None:
        """Record a valid current message while the state lock is held."""

        self._message_sequence += 1
        self._device_seen_sequence[device_id] = self._message_sequence

    def _schedule_probe(self, message: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            return
        endpoint = (message["ip"], message["rtsp_port"], message["rtsp_path"])
        token = message["message_id"]
        run_generation = self._run_generation
        with self._state_lock:
            existing = self._inflight.get(message["device_id"])
            if existing is not None and existing[2] == endpoint:
                return
            self._inflight[message["device_id"]] = (
                run_generation,
                token,
                endpoint,
            )
        with self._lifecycle_lock:
            executor = self._executor
        if executor is None:
            with self._state_lock:
                if self._inflight.get(message["device_id"]) == (
                    run_generation,
                    token,
                    endpoint,
                ):
                    self._inflight.pop(message["device_id"], None)
            return
        if not self._probe_slots.acquire(blocking=False):
            with self._state_lock:
                if self._inflight.get(message["device_id"]) == (
                    run_generation,
                    token,
                    endpoint,
                ):
                    self._inflight.pop(message["device_id"], None)
            LOGGER.debug("probe queue is full; ignored %s", message["device_id"])
            return
        try:
            future = executor.submit(
                self._run_probe,
                run_generation,
                message["device_id"],
                token,
                endpoint,
            )
        except RuntimeError:
            self._probe_slots.release()
            with self._state_lock:
                if self._inflight.get(message["device_id"]) == (
                    run_generation,
                    token,
                    endpoint,
                ):
                    self._inflight.pop(message["device_id"], None)
        else:
            future.add_done_callback(lambda _future: self._probe_slots.release())

    def _run_probe(
        self,
        run_generation: int,
        device_id: str,
        token: str,
        endpoint: tuple[str, int, str],
    ) -> None:
        self._probe_worker_context.active = True
        try:
            try:
                succeeded = bool(self._rtsp_probe(*endpoint, self.rtsp_timeout))
            except Exception:
                LOGGER.debug("RTSP probe failed with an exception", exc_info=True)
                succeeded = False
            self._probe_results.put(
                (run_generation, device_id, token, endpoint, succeeded)
            )
        finally:
            self._probe_worker_context.active = False

    def _drain_probe_results(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._probe_results.get_nowait()
            except queue.Empty:
                return
            self._complete_probe(*result)

    def _complete_probe(
        self,
        run_generation: int,
        device_id: str,
        token: str,
        endpoint: tuple[str, int, str],
        succeeded: bool,
    ) -> None:
        if run_generation != self._run_generation:
            return
        callback_payload: dict[str, Any] | None = None
        with self._state_lock:
            if self._inflight.get(device_id) != (
                run_generation,
                token,
                endpoint,
            ):
                return
            self._inflight.pop(device_id, None)
            current = self._devices.get(device_id)
            if current is None:
                return
            current_endpoint = (
                current["ip"], current["rtsp_port"], current["rtsp_path"]
            )
            if current_endpoint != endpoint:
                return
            current["rtsp_connected"] = succeeded
            if succeeded:
                self._last_probe_success[device_id] = time.monotonic()
            else:
                self._last_probe_success.pop(device_id, None)
                self._reported_endpoints.pop(device_id, None)
            if succeeded and self._reported_endpoints.get(device_id) != endpoint:
                self._reported_endpoints[device_id] = endpoint
                callback_payload = copy.deepcopy(current)

        if callback_payload is not None:
            self._invoke_callback(callback_payload)

    def _invoke_callback(self, payload: dict[str, Any]) -> None:
        if self.on_device is not None:
            try:
                self.on_device(copy.deepcopy(payload))
            except Exception:
                LOGGER.exception("on_device callback failed")

    def _send_ack(self, message: dict[str, Any], peer: tuple[str, int]) -> None:
        ack = make_message(
            MessageType.ACK,
            device_id=message["device_id"],
            ip=message["ip"],
            rtsp_port=message["rtsp_port"],
            rtsp_path=message["rtsp_path"],
            ack_for=message["message_id"],
        )
        try:
            payload = encode_message(ack)
        except MessageError:
            return
        with self._lifecycle_lock:
            udp_socket = self._socket
        if udp_socket is None:
            return
        try:
            udp_socket.sendto(payload, peer)
        except OSError:
            if not self._stop_event.is_set():
                LOGGER.debug("could not send ACK to %s:%s", *peer, exc_info=True)

    def __enter__(self) -> "BootstrapReceiver":
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
