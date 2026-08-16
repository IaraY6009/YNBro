# YNB

`YNB`는 동일 IPv4 LAN에서 RTSP 연결정보를 UDP broadcast로 전달하고,
Receiver가 해당 RTSP endpoint에 `RTSP/2.0 OPTIONS` 요청을 보내
접속 가능 여부를 확인하는 Python 패키지입니다.

현재 버전은 **0.0.1 PoC**이며 RTSP 영상 재생은 수행하지 않습니다.

## 환경

- Python 3.11.9
- IPv4 동일 broadcast domain
- 외부 runtime dependency 없음
- 기본 UDP port: `37020`

## 설치

프로젝트 루트에서 실행합니다.

```powershell
python --version
python -m pip install -e .
```

`python --version`은 `Python 3.11.9`여야 합니다.

## 동작 흐름

```text
Sender
  |
  | UDP broadcast
  | device_id, ip, rtsp_port, rtsp_path
  v
Receiver
  |
  | TCP
  | RTSP/2.0 OPTIONS
  v
RTSP Server
  |
  v
Receiver가 결과 dict 반환
```

## 사용

### Sender

```python
from ynb import sender

sender.broadcast(
    device_id="DC:A6:32:12:34:56",  //MAC address
    ip="192.168.0.10",
    rtsp_port=8554,
    rtsp_path="/stream",
)
```

### Receiver

```python
from ynb import receiver

device = receiver.discover(timeout=5)

print(device)
```

예상 결과:

```python
{
    "device_id": "DC:A6:32:12:34:56",
    "ip": "192.168.0.10",
    "rtsp_port": 8554,
    "rtsp_path": "/stream",
    "rtsp_uri": "rtsp://192.168.0.10:8554/stream",
    "rtsp_connected": True,
}
```

`rtsp_connected=True`는 RTSP 서버가 `RTSP/2.0 OPTIONS` 요청에 정상적인
`2xx` 응답을 반환했다는 의미입니다. 실제 영상 재생 성공을 의미하지 않습니다.

## 패키지 구조

```text
src/ynb/
├── __init__.py
├── sender.py
├── receiver.py
└── connecter.py
```

- `sender.py`: RTSP 연결정보 UDP broadcast
- `receiver.py`: 광고 수신 및 발견 결과 반환
- `connecter.py`: RTSP URI 생성 및 RTSP/2.0 probe

## 0.0.1 메시지

Sender는 다음 JSON 데이터를 하나의 UDP 데이터그램으로 전송합니다.

```json
{
  "device_id"="DC:A6:32:12:34:56",  //MAC address
  "ip": "192.168.0.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

## 테스트

```powershell
python -m unittest discover -s tests -v
```

최소한 다음을 검증합니다.

- UDP 광고 송수신
- RTSP/2.0 `OPTIONS` probe 성공/실패
- Sender → Receiver → 가짜 RTSP 서버 전체 흐름

## 현재 범위 밖

0.0.1에서는 다음 기능을 제공하지 않습니다.

- ACK / DETAIL
- `message_id`
- 메시지 재전송 및 중복 제거
- callback
- 장비 registry
- 비동기 probe 및 worker thread
- RTSP 영상 재생
- 인증 및 암호화
- 다른 subnet 또는 인터넷을 통한 자동 발견

상세 요구사항은 [`SRS.md`](SRS.md)를 참고하십시오.