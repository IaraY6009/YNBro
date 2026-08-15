from __future__ import annotations

import queue
import socket
import threading


class FakeRtspServer:
    def __init__(
        self,
        response: bytes = (
            b"RTSP/2.0 200 OK\r\n"
            b"CSeq: 1\r\n"
            b"Public: OPTIONS, DESCRIBE, SETUP, PLAY\r\n"
            b"\r\n"
        ),
    ) -> None:
        self.response = response
        self.requests: queue.Queue[bytes] = queue.Queue()
        self._stop = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self._socket.settimeout(0.1)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _peer = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(1.0)
                request = bytearray()
                try:
                    while b"\r\n\r\n" not in request:
                        chunk = connection.recv(4_096)
                        if not chunk:
                            break
                        request.extend(chunk)
                    self.requests.put(bytes(request))
                    connection.sendall(self.response)
                except OSError:
                    pass

    def close(self) -> None:
        self._stop.set()
        self._socket.close()
        self._thread.join(1.0)


def udp_client() -> socket.socket:
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.bind(("127.0.0.1", 0))
    client.settimeout(2.0)
    return client
