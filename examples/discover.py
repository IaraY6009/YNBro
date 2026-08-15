import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rtsp_discovery import discover_rtsp_devices


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover RTSP devices on the local LAN.")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--discovery-port", type=int, default=37020)
    parser.add_argument("--packet-number", type=int, default=0)
    args = parser.parse_args()

    devices = discover_rtsp_devices(
        timeout=args.timeout,
        discovery_port=args.discovery_port,
        packet_number=args.packet_number,
    )

    if not devices:
        print("No RTSP devices found.")
        return

    for device in devices:
        print(
            f"{device.ip}:{device.port} "
            f"mac={device.mac} packet_number={device.packet_number} "
            f"(response from {device.source_ip}:{device.source_port})"
        )


if __name__ == "__main__":
    main()
