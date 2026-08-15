import socket


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 8554))
    server.listen()
    print("fake RTSP server: rtsp://127.0.0.1:8554/stream")

    while True:
        connection, peer = server.accept()
        with connection:
            request = b""
            while b"\r\n\r\n" not in request and len(request) < 16_384:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                request += chunk

            first_line = request.split(b"\r\n", 1)[0]
            print(peer, first_line.decode("ascii", errors="replace"))
            connection.sendall(
                b"RTSP/2.0 200 OK\r\n"
                b"CSeq: 1\r\n"
                b"Content-Length: 0\r\n"
                b"\r\n"
            )
