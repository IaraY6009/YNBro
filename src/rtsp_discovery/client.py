from dataclasses import dataclass
import socket
import time

from .protocol import DISCOVERY_PORT, MAX_PACKET_SIZE, make_request, parse_response


@dataclass(frozen=True)
class DiscoveryResult:
    ip: str
    port: int
    mac: str
    packet_number: int
    source_ip: str
    source_port: int


def discover_rtsp_devices(
    *,
    discovery_port: int = DISCOVERY_PORT,
    timeout: float = 2.0,
    broadcast_address: str = "255.255.255.255",
    packet_number: int = 0,
) -> list[DiscoveryResult]:
    """Broadcast an RTSP discovery request and collect JSON responses."""
    deadline = time.monotonic() + timeout
    results: list[DiscoveryResult] = []
    seen: set[tuple[str, int, str]] = set()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(min(timeout, 0.2))
        sock.sendto(make_request(packet_number), (broadcast_address, discovery_port))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            sock.settimeout(min(remaining, 0.2))
            try:
                data, addr = sock.recvfrom(MAX_PACKET_SIZE)
            except TimeoutError:
                continue

            try:
                packet = parse_response(data)
            except ValueError:
                continue

            key = (packet["ip"], packet["port"], packet["mac"])
            if key in seen:
                continue
            seen.add(key)

            results.append(
                DiscoveryResult(
                    ip=packet["ip"],
                    port=packet["port"],
                    mac=packet["mac"],
                    packet_number=packet["packet_number"],
                    source_ip=addr[0],
                    source_port=addr[1],
                )
            )

    return results
