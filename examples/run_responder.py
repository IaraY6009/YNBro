import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rtsp_discovery import RtspDiscoveryResponder


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a test RTSP discovery responder.")
    parser.add_argument("--rtsp-port", type=int, default=8554)
    parser.add_argument("--discovery-port", type=int, default=37020)
    parser.add_argument("--advertised-ip")
    parser.add_argument("--mac")
    args = parser.parse_args()

    responder = RtspDiscoveryResponder(
        rtsp_port=args.rtsp_port,
        discovery_port=args.discovery_port,
        advertised_ip=args.advertised_ip,
        mac=args.mac,
    )

    print(
        "RTSP discovery responder listening "
        f"on UDP :{args.discovery_port}, advertising port {args.rtsp_port}"
    )
    responder.serve_forever()


if __name__ == "__main__":
    main()
