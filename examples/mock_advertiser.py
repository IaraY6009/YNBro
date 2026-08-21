from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

from rtsp_discovery.receiver import (  # noqa: E402
    ACK_TYPE,
    MAX_PACKET_SIZE,
)


PROTOCOL_VERSION = 1
ADVERTISE_TYPE = "ADVERTISE"
DETAIL_TYPE = "DETAIL"


def encode(packet: dict) -> bytes:
    return json.dumps(
        packet,
        separators=(",", ":"),
    ).encode("utf-8")


def receive_ack(
    sock: socket.socket,
    expected_message_id: str,
) -> None:
    sock.settimeout(3.0)

    try:
        while True:
            data, address = sock.recvfrom(MAX_PACKET_SIZE)
            packet = json.loads(data.decode("utf-8"))

            if packet.get("type") != ACK_TYPE:
                print(f"ACK가 아닌 패킷 수신: {packet}")
                continue

            if packet.get("in_reply_to") != expected_message_id:
                print(f"다른 메시지의 ACK 수신: {packet}")
                continue

            print(
                "ACK 수신 성공:",
                f"from={address[0]}:{address[1]}",
                f"in_reply_to={packet['in_reply_to']}",
                f"status={packet['status']}",
                f"receiver_id={packet['receiver_id']}",
            )
            return

    except socket.timeout:
        print(
            "ACK 수신 시간 초과:",
            f"message_id={expected_message_id}",
        )


def send_message_and_wait_ack(
    *,
    sock: socket.socket,
    message: dict,
    destination: tuple[str, int],
) -> None:
    message_id = message["message_id"]
    data = encode(message)

    print("\n메시지 전송:")
    print(json.dumps(message, indent=2))

    sock.sendto(data, destination)
    receive_ack(sock, message_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mock RTSP advertisement sender"
    )

    parser.add_argument(
        "--receiver-ip",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--receiver-port",
        type=int,
        default=37020,
    )
    parser.add_argument(
        "--device-id",
        default="camera-mock-01",
    )
    parser.add_argument(
        "--device-ip",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--rtsp-port",
        type=int,
        default=8554,
    )
    parser.add_argument(
        "--mac",
        default="00:11:22:33:44:55",
    )
    parser.add_argument(
        "--stream-path",
        default="stream1",
    )

    args = parser.parse_args()

    destination = (
        args.receiver_ip,
        args.receiver_port,
    )

    with socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    ) as sock:
        sock.bind(("127.0.0.1", 0))

        advertise_message = {
            "type": ADVERTISE_TYPE,
            "version": PROTOCOL_VERSION,
            "message_id": str(uuid.uuid4()),
            "device_id": args.device_id,
            "ip": args.device_ip,
            "rtsp_port": args.rtsp_port,
            "mac": args.mac,
        }

        send_message_and_wait_ack(
            sock=sock,
            message=advertise_message,
            destination=destination,
        )

        time.sleep(0.5)

        detail_message = {
            "type": DETAIL_TYPE,
            "version": PROTOCOL_VERSION,
            "message_id": str(uuid.uuid4()),
            "device_id": args.device_id,
            "stream_path": args.stream_path,
        }

        send_message_and_wait_ack(
            sock=sock,
            message=detail_message,
            destination=destination,
        )


if __name__ == "__main__":
    main()
