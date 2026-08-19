"""동일한 IPv4 LAN에서 RTSP 접속 정보를 교환하는 YNB 0.0.1 패키지.

공개 API로 ``sender``와 ``receiver`` 모듈을 제공한다.
"""

from . import receiver, sender

__all__ = ["receiver", "sender"]
__version__ = "0.0.1"
