import socket
from threading import Event
import uuid

from .protocol import DISCOVERY_PORT, MAX_PACKET_SIZE, make_response, parse_request


class RtspDiscoveryResponder:
    def __init__(
        self,
        *,
        rtsp_port: int,
        discovery_port: int = DISCOVERY_PORT,
        advertised_ip: str | None = None,
        mac: str | None = None,
    ) -> None:
        self.rtsp_port = rtsp_port
        self.discovery_port = discovery_port
        self.advertised_ip = advertised_ip
        self.mac = mac or _get_local_mac()
        self._stop_event = Event()

    def stop(self) -> None:
        self._stop_event.set()

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(0.2)

            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(MAX_PACKET_SIZE)
                except TimeoutError:
                    continue

                try:
                    request = parse_request(data)
                except ValueError:
                    continue

                ip = self.advertised_ip or _guess_local_ip(addr[0])
                response_packet_number = request["packet_number"] + 1
                response = make_response(
                    ip,
                    self.rtsp_port,
                    self.mac,
                    response_packet_number,
                )
                sock.sendto(response, addr)


def _guess_local_ip(remote_ip: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect((remote_ip, 1))
            return sock.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


def _get_local_mac() -> str:
    value = uuid.getnode()
    pairs = [f"{(value >> shift) & 0xff:02x}" for shift in range(40, -1, -8)]
    return ":".join(pairs)
