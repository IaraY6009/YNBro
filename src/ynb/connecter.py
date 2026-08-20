"""RTSP endpoint helpers contributed by the receiver branch."""

from __future__ import annotations

from urllib.parse import quote

from ._protocol import validate_ipv4, validate_port, validate_rtsp_path


def build_rtsp_uri(ip: str, rtsp_port: int, rtsp_path: str) -> str:
    """Build the RTSP URI represented by a validated DETAIL endpoint."""

    host = validate_ipv4(ip)
    port = validate_port(rtsp_port)
    path = validate_rtsp_path(rtsp_path)
    return f"rtsp://{host}:{port}{quote(path, safe='/')}"


def probe_rtsp(
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    timeout: float,
) -> bool:
    """Probe support was not implemented by either merged feature branch."""

    raise NotImplementedError("RTSP probe is not implemented")
