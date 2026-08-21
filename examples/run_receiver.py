from __future__ import annotations

import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

from rtsp_discovery import RTSPAdvertisementReceiver  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(name)s] %(levelname)s: %(message)s",
)


def main() -> None:
    receiver = RTSPAdvertisementReceiver(
        listen_port=37020,
        receiver_id="receiver-01",
    )

    try:
        receiver.serve_forever()
    except KeyboardInterrupt:
        print("\nReceiver stopped.")
        receiver.stop()


if __name__ == "__main__":
    main()
