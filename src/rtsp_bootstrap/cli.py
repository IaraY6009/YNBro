"""Command-line interfaces for the sender and receiver."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import threading
from collections.abc import Sequence
from typing import Any

from .receiver import BootstrapReceiver
from .sender import BootstrapSender


def _json_object(value: str) -> dict[str, object]:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite number: {constant}")

    try:
        parsed = json.loads(value, parse_constant=reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _port(value: str, *, allow_zero: bool = False) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    minimum = 0 if allow_zero else 1
    if not minimum <= parsed <= 65_535:
        range_text = "0 to 65535" if allow_zero else "1 to 65535"
        raise argparse.ArgumentTypeError(f"must be from {range_text}")
    return parsed


def _network_port(value: str) -> int:
    return _port(value)


def _bind_port(value: str) -> int:
    return _port(value, allow_zero=True)


def _add_logging_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="WARNING",
    )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _add_sender_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--ip", required=True, help="advertised RTSP server IPv4 address")
    parser.add_argument("--rtsp-port", required=True, type=_network_port)
    parser.add_argument("--rtsp-path", required=True)
    parser.add_argument("--port", dest="discovery_port", type=_network_port, default=37_020,
                        help="UDP bootstrap destination port (default: 37020)")
    parser.add_argument("--broadcast-address", default="255.255.255.255")
    parser.add_argument("--interval", type=_positive_float, default=2.0)
    parser.add_argument("--detail-json", type=_json_object, default={})
    parser.add_argument("--bind", dest="bind_host", default="0.0.0.0")
    parser.add_argument("--bind-port", type=_bind_port, default=0)
    parser.add_argument(
        "--duration",
        type=_nonnegative_float,
        help="stop after this many seconds instead of running until Ctrl-C",
    )
    _add_logging_argument(parser)


def _add_receiver_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bind", dest="bind_host", default="0.0.0.0")
    parser.add_argument("--port", dest="discovery_port", type=_bind_port, default=37_020,
                        help="UDP bootstrap listen port (default: 37020)")
    parser.add_argument("--rtsp-timeout", type=_positive_float, default=2.0)
    parser.add_argument(
        "--duration",
        type=_nonnegative_float,
        help="stop after this many seconds instead of running until Ctrl-C",
    )
    _add_logging_argument(parser)


def _print_device(device: dict[str, Any]) -> None:
    print(json.dumps(device, ensure_ascii=False, sort_keys=True), flush=True)


def _configure_utf8_stdout() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="strict")


def _run_sender(args: argparse.Namespace) -> int:
    _configure_logging(args.log_level)
    sender = BootstrapSender(
        device_id=args.device_id,
        ip=args.ip,
        rtsp_port=args.rtsp_port,
        rtsp_path=args.rtsp_path,
        details=args.detail_json,
        discovery_port=args.discovery_port,
        broadcast_address=args.broadcast_address,
        advertise_interval=args.interval,
        bind_host=args.bind_host,
        bind_port=args.bind_port,
    )
    try:
        if args.duration is None:
            sender.serve_forever()
        else:
            sender.start()
            threading.Event().wait(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        sender.stop()
    return 0


def _run_receiver(args: argparse.Namespace) -> int:
    _configure_logging(args.log_level)
    _configure_utf8_stdout()
    receiver = BootstrapReceiver(
        bind_host=args.bind_host,
        discovery_port=args.discovery_port,
        rtsp_timeout=args.rtsp_timeout,
        on_device=_print_device,
    )
    try:
        if args.duration is None:
            receiver.serve_forever()
        else:
            receiver.discover(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
    return 0


def sender_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rtsp-bootstrap-sender",
        description="Broadcast RTSP bootstrap connection information.",
    )
    _add_sender_arguments(parser)
    try:
        return _run_sender(parser.parse_args(argv))
    except ValueError as exc:
        parser.error(str(exc))


def receiver_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rtsp-bootstrap-receiver",
        description="Discover and verify RTSP bootstrap devices.",
    )
    _add_receiver_arguments(parser)
    try:
        return _run_receiver(parser.parse_args(argv))
    except ValueError as exc:
        parser.error(str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rtsp_bootstrap",
        description="RTSP connection-information bootstrap protocol.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    sender_parser = subparsers.add_parser("sender", help="run a periodic advertiser")
    _add_sender_arguments(sender_parser)
    receiver_parser = subparsers.add_parser("receiver", help="run a discovery receiver")
    _add_receiver_arguments(receiver_parser)
    args = parser.parse_args(argv)
    try:
        if args.command == "sender":
            return _run_sender(args)
        return _run_receiver(args)
    except ValueError as exc:
        parser.error(str(exc))
