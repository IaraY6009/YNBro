"""Periodic UDP advertiser for RTSP bootstrap discovery."""

from __future__ import annotations

import copy
import ipaddress
import logging
import math
import socket
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Mapping

from .protocol import (
    MAX_DATAGRAM_SIZE,
    MessageError,
    MessageType,
    decode_message,
    encode_message,
    make_message,
)

LOGGER = logging.getLogger(__name__)

AckCallback = Callable[[dict[str, Any]], None]


class BootstrapSender:
    """Broadcast connection information and unicast details to receivers."""

    def __init__(
        self,
        *,
        device_id: str,
        ip: str,
        rtsp_port: int,
        rtsp_path: str,
        details: Mapping[str, object] | None = None,
        discovery_port: int = 37_020,
        broadcast_address: str = "255.255.255.255",
        advertise_interval: float = 2.0,
        bind_host: str = "0.0.0.0",
        bind_port: int = 0,
        on_detail_ack: AckCallback | None = None,
        history_capacity: int = 4_096,
    ) -> None:
        if not isinstance(discovery_port, int) or isinstance(discovery_port, bool):
            raise ValueError("discovery_port must be an integer")
        if not 1 <= discovery_port <= 65_535:
            raise ValueError("discovery_port must be from 1 to 65535")
        if not isinstance(bind_port, int) or isinstance(bind_port, bool):
            raise ValueError("bind_port must be an integer")
        if not 0 <= bind_port <= 65_535:
            raise ValueError("bind_port must be from 0 to 65535")
        if (
            isinstance(advertise_interval, bool)
            or not isinstance(advertise_interval, (int, float))
            or not math.isfinite(advertise_interval)
            or advertise_interval <= 0
        ):
            raise ValueError("advertise_interval must be greater than zero")
        if (
            isinstance(history_capacity, bool)
            or not isinstance(history_capacity, int)
            or history_capacity < 1
        ):
            raise ValueError("history_capacity must be at least one")
        if details is not None and not isinstance(details, Mapping):
            raise ValueError("details must be a mapping")

        try:
            self.broadcast_address = str(ipaddress.IPv4Address(broadcast_address))
        except (ipaddress.AddressValueError, TypeError) as exc:
            raise ValueError("broadcast_address must be a valid IPv4 address") from exc

        # Validate endpoint fields, arbitrary JSON values, and UDP size before
        # starting a background thread.
        detail_message = make_message(
            MessageType.DETAIL,
            device_id=device_id,
            ip=ip,
            rtsp_port=rtsp_port,
            rtsp_path=rtsp_path,
            in_reply_to="validation",
            details=dict(details or {}),
        )
        encode_message(detail_message)

        self.device_id = device_id
        self.ip = ip
        self.rtsp_port = rtsp_port
        self.rtsp_path = rtsp_path
        self.details = copy.deepcopy(detail_message["details"])
        self.discovery_port = discovery_port
        self.advertise_interval = float(advertise_interval)
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.on_detail_ack = on_detail_ack
        self._history_capacity = history_capacity

        self._state_lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._ack_condition = threading.Condition(self._state_lock)
        self._advertisements: OrderedDict[str, None] = OrderedDict()
        self._handled_advertisement_acks: OrderedDict[
            tuple[str, str, int], None
        ] = OrderedDict()
        self._pending_details: OrderedDict[str, tuple[str, int]] = OrderedDict()
        self._detail_acks: OrderedDict[str, dict[str, Any]] = OrderedDict()

        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._local_address: tuple[str, int] | None = None
        self._start_error: BaseException | None = None
        self._run_generation = 0
        self._cancelled_generation = -1

    @property
    def local_address(self) -> tuple[str, int] | None:
        with self._lifecycle_lock:
            return self._local_address

    @property
    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._running

    def start(self, *, startup_timeout: float = 3.0) -> "BootstrapSender":
        """Run the sender in a background thread and wait until bind completes."""

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
                    self._ready_event.clear()
                    self._start_error = None
                    self._run_generation += 1
                    with self._state_lock:
                        self._advertisements.clear()
                        self._handled_advertisement_acks.clear()
                        self._pending_details.clear()
                    thread = threading.Thread(
                        target=self._background_main,
                        name="rtsp-bootstrap-sender",
                        daemon=True,
                    )
                    self._thread = thread
                    thread.start()
                    break
            if stopping_thread is threading.current_thread():
                raise RuntimeError("cannot restart sender while it is stopping")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("previous sender run did not stop")
            stopping_thread.join(remaining)
            if stopping_thread.is_alive():
                raise TimeoutError("previous sender run did not stop")

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._ready_event.wait(remaining):
            self.stop()
            raise TimeoutError("sender did not start before the timeout")
        if self._start_error is not None:
            error = self._start_error
            self.stop()
            raise RuntimeError("sender could not bind its UDP socket") from error
        return self

    def _background_main(self) -> None:
        try:
            self._serve(prepared=True)
        except BaseException:
            if self._start_error is None:
                LOGGER.exception("sender background thread stopped unexpectedly")

    def serve_forever(self) -> None:
        """Advertise periodically and service ACKs until stopped."""

        self._serve(prepared=False)

    def _serve(self, *, prepared: bool) -> None:
        current_thread = threading.current_thread()
        with self._lifecycle_lock:
            if self._running:
                raise RuntimeError("sender is already running")
            self._running = True
            if not prepared:
                self._stop_event.clear()
                self._ready_event.clear()
                self._start_error = None
                self._run_generation += 1
                with self._state_lock:
                    self._advertisements.clear()
                    self._handled_advertisement_acks.clear()
                    self._pending_details.clear()
                self._thread = current_thread
            self._local_address = None

        udp_socket: socket.socket | None = None
        try:
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp_socket.bind((self.bind_host, self.bind_port))
            with self._lifecycle_lock:
                self._socket = udp_socket
                bound_host, bound_port = udp_socket.getsockname()[:2]
                self._local_address = (str(bound_host), int(bound_port))
            self._ready_event.set()

            next_advertisement = 0.0
            while not self._stop_event.is_set():
                now = time.monotonic()
                if now >= next_advertisement:
                    try:
                        self._send_advertisement(udp_socket)
                    except (OSError, MessageError):
                        if not self._stop_event.is_set():
                            LOGGER.warning(
                                "could not send ADVERTISE", exc_info=True
                            )
                    next_advertisement = now + self.advertise_interval

                remaining = max(0.01, min(0.2, next_advertisement - time.monotonic()))
                udp_socket.settimeout(remaining)
                try:
                    payload, peer = udp_socket.recvfrom(MAX_DATAGRAM_SIZE + 1)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    LOGGER.debug("transient UDP receive failure", exc_info=True)
                    continue
                try:
                    self._handle_ack(
                        payload, (str(peer[0]), int(peer[1])), udp_socket
                    )
                except Exception:
                    LOGGER.exception("ignored bootstrap ACK after handler error")
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
            with self._lifecycle_lock:
                self._socket = None
                self._running = False
                self._cancelled_generation = max(
                    self._cancelled_generation, self._run_generation
                )
                if self._thread is current_thread:
                    self._thread = None
            with self._ack_condition:
                self._ack_condition.notify_all()
            self._ready_event.set()

    def stop(self, *, wait: bool = True, timeout: float | None = None) -> None:
        self._stop_event.set()
        with self._lifecycle_lock:
            self._cancelled_generation = max(
                self._cancelled_generation, self._run_generation
            )
            thread = self._thread
        with self._ack_condition:
            self._ack_condition.notify_all()
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout)

    close = stop

    def advertise_once(self) -> str:
        """Immediately send one advertisement from the running sender."""

        with self._lifecycle_lock:
            udp_socket = self._socket
        if udp_socket is None or self._stop_event.is_set():
            raise RuntimeError("sender is not running")
        return self._send_advertisement(udp_socket)

    def send_detail(
        self, peer: tuple[str, int], *, in_reply_to: str
    ) -> str:
        """Send one DETAIL message to a receiver and return its message ID."""

        with self._lifecycle_lock:
            udp_socket = self._socket
        if udp_socket is None or self._stop_event.is_set():
            raise RuntimeError("sender is not running")
        return self._send_detail(udp_socket, peer, in_reply_to)

    def wait_for_ack(
        self, message_id: str, timeout: float | None = None
    ) -> dict[str, Any] | None:
        """Wait for a DETAIL ACK, returning ``None`` on timeout."""

        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")
        if timeout is not None and not math.isfinite(timeout):
            raise ValueError("timeout must be finite")
        deadline = None if timeout is None else time.monotonic() + timeout
        wait_generation = self._run_generation
        with self._ack_condition:
            while message_id not in self._detail_acks:
                if (
                    self._cancelled_generation >= wait_generation
                    or self._run_generation != wait_generation
                ):
                    return None
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._ack_condition.wait(remaining)
            return copy.deepcopy(self._detail_acks[message_id])

    def get_detail_acks(self) -> dict[str, dict[str, Any]]:
        with self._state_lock:
            return copy.deepcopy(dict(self._detail_acks))

    def _bounded_add(self, mapping: OrderedDict[Any, Any], key: Any, value: Any) -> None:
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > self._history_capacity:
            mapping.popitem(last=False)

    def _send_advertisement(self, udp_socket: socket.socket) -> str:
        message = make_message(
            MessageType.ADVERTISE,
            device_id=self.device_id,
            ip=self.ip,
            rtsp_port=self.rtsp_port,
            rtsp_path=self.rtsp_path,
        )
        payload = encode_message(message)
        with self._state_lock:
            self._bounded_add(self._advertisements, message["message_id"], None)
        try:
            udp_socket.sendto(
                payload, (self.broadcast_address, self.discovery_port)
            )
        except OSError:
            with self._state_lock:
                self._advertisements.pop(message["message_id"], None)
            raise
        return str(message["message_id"])

    def _send_detail(
        self,
        udp_socket: socket.socket,
        peer: tuple[str, int],
        in_reply_to: str,
    ) -> str:
        message = make_message(
            MessageType.DETAIL,
            device_id=self.device_id,
            ip=self.ip,
            rtsp_port=self.rtsp_port,
            rtsp_path=self.rtsp_path,
            in_reply_to=in_reply_to,
            details=self.details,
        )
        payload = encode_message(message)
        with self._state_lock:
            self._bounded_add(self._pending_details, message["message_id"], peer)
        try:
            udp_socket.sendto(payload, peer)
        except OSError:
            with self._state_lock:
                if self._pending_details.get(message["message_id"]) == peer:
                    self._pending_details.pop(message["message_id"], None)
            raise
        return str(message["message_id"])

    def _handle_ack(
        self,
        payload: bytes,
        peer: tuple[str, int],
        udp_socket: socket.socket,
    ) -> None:
        try:
            message = decode_message(payload)
        except (MessageError, RecursionError):
            return
        if message["message_type"] != MessageType.ACK.value:
            return
        if message["device_id"] != self.device_id:
            return
        if (
            message["ip"],
            message["rtsp_port"],
            message["rtsp_path"],
        ) != (self.ip, self.rtsp_port, self.rtsp_path):
            return

        ack_for = message["ack_for"]
        callback_payload: dict[str, Any] | None = None
        with self._state_lock:
            if ack_for in self._advertisements:
                response_key = (ack_for, peer[0], peer[1])
                if response_key in self._handled_advertisement_acks:
                    return
                self._bounded_add(
                    self._handled_advertisement_acks, response_key, None
                )
            elif ack_for in self._pending_details:
                expected_peer = self._pending_details[ack_for]
                if expected_peer != peer:
                    return
                if ack_for in self._detail_acks:
                    return
                callback_payload = {
                    "message_id": ack_for,
                    "peer": {"ip": peer[0], "port": peer[1]},
                    "ack": copy.deepcopy(message),
                }
                self._bounded_add(self._detail_acks, ack_for, callback_payload)
                self._ack_condition.notify_all()
            else:
                return

        if callback_payload is None:
            try:
                self._send_detail(udp_socket, peer, ack_for)
            except (OSError, MessageError):
                if not self._stop_event.is_set():
                    LOGGER.debug("could not send DETAIL", exc_info=True)
            return

        if self.on_detail_ack is not None:
            try:
                self.on_detail_ack(copy.deepcopy(callback_payload))
            except Exception:
                LOGGER.exception("on_detail_ack callback failed")

    def __enter__(self) -> "BootstrapSender":
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop()
