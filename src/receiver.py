import asyncio
import json
import logging
from typing import Tuple, Optional, Dict, Any

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][BootstrapReceiver] %(levelname)s: %(message)s"
)
logger = logging.getLogger("BootstrapReceiver")


class BootstrapReceiverProtocol(asyncio.DatagramProtocol):
    """
    BootstrapSender의 ADVERTISE 및 DETAIL 패킷을 수신하고 ACK를 응답하는 프로토콜
    """
    def __init__(self):
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        logger.info("UDP 수신 소켓이 준비되었습니다.")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        """
        UDP 패킷 수신 시 호출되는 콜백 함수
        """
        try:
            # 1. 수신된 JSON 데이터 파싱
            message: Dict[str, Any] = json.loads(data.decode('utf-8'))
            msg_type = message.get("type")
            msg_id = message.get("message_id")

            # message_id 유효성 검증
            if not msg_id:
                logger.warning(f"message_id가 없는 비정상 패킷 수신 무시: {addr}")
                return

            # 2. ADVERTISE 수신 확인 및 ACK 회신
            if msg_type == "ADVERTISE":
                logger.info(f"[ADVERTISE 수신] ID: {msg_id} | 발신지: {addr}")
                self._send_ack(ack_for=msg_id, target_addr=addr)

            # 3. DETAIL 수신 확인 및 ACK 회신
            elif msg_type == "DETAIL":
                in_reply_to = message.get("in_reply_to")
                logger.info(f"[DETAIL 수신] ID: {msg_id} (in_reply_to: {in_reply_to}) | 발신지: {addr}")
                self._send_ack(ack_for=msg_id, target_addr=addr)

            else:
                logger.warning(f"알 수 없는 메시지 타입 수신: {msg_type} from {addr}")

        except json.JSONDecodeError:
            logger.error(f"JSON 디코딩 실패 (잘못된 데이터 포맷): {data} from {addr}")
        except Exception as e:
            logger.error(f"수신 데이터 처리 중 예외 발생: {e}")

    def _send_ack(self, ack_for: str, target_addr: Tuple[str, int]):
        """
        다이어그램 규격에 맞는 UDP Unicast ACK 응답 전송
        """
        ack_packet = {
            "type": "ACK",
            "ack_for": ack_for
        }
        ack_bytes = json.dumps(ack_packet).encode('utf-8')
        
        if self.transport:
            self.transport.sendto(ack_bytes, target_addr)
            logger.info(f"[ACK 전송] ack_for: {ack_for} -> {target_addr}")


class BootstrapReceiver:
    """
    수신 대기 및 소켓 생명주기 관리 클래스
    """
    def __init__(self, listen_host: str = "0.0.0.0", listen_port: int = 50000):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.transport: Optional[asyncio.DatagramTransport] = None

    async def start(self):
        """수신 서버 시작"""
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: BootstrapReceiverProtocol(),
            local_addr=(self.listen_host, self.listen_port),
            allow_broadcast=True
        )
        logger.info(f"BootstrapReceiver가 {self.listen_host}:{self.listen_port} 에서 대기 중입니다.")

    def stop(self):
        """소켓 종료"""
        if self.transport:
            self.transport.close()
            logger.info("BootstrapReceiver가 안전하게 종료되었습니다.")


# =========================================================
# 단독 실행 및 테스트용 메인 블록
# =========================================================
async def main():
    # 기본 수신 포트: 50000 (팀 규약에 맞게 변경 가능)
    receiver = BootstrapReceiver(listen_port=50000)
    await receiver.start()

    try:
        # 종료 전까지 백그라운드에서 계속 패킷 수신 및 ACK 전송
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        receiver.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")