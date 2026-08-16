# YNB

`YNB`는 동일 IPv4 LAN에서 RTSP 장비를 UDP broadcast로 발견하고,
RTSP 연결정보를 전달받아 해당 RTSP/2.0 서버의 응답 여부를 확인하는
Python 패키지입니다.

현재 버전은 **0.0.1 PoC**입니다.

## 환경

* Python 3.11.9
* RTSP 2.0
* IPv4 동일 broadcast domain
* 기본 UDP port: `37020`
* 외부 runtime dependency 없음

## 동작 방식

YNB 0.0.1은 다음 순서로 동작합니다.

```text
Sender                         Receiver                    RTSP Server
  |                               |                            |
  |--- ADVERTISE broadcast ------>|                            |
  |<------ ACK unicast -----------|                            |
  |------- DETAIL unicast ------->|                            |
  |<------ ACK unicast -----------|                            |
  |                               |------- TCP connect ------->|
  |                               |------- RTSP OPTIONS ------>|
  |                               |<------ RTSP/2.0 2xx -------|
```

### 1. ADVERTISE

Sender는 자신의 존재를 최소한의 정보만 포함하여 broadcast합니다.

```json
{
  "message_type": "ADVERTISE",
  "device_id": "DC:A6:32:12:34:56"
}
```

0.0.1에서는 `device_id`로 MAC 주소를 사용합니다.

### 2. ADVERTISE ACK

Receiver는 ADVERTISE를 수신하면 해당 UDP 데이터그램의 실제 발신 주소로 ACK를 unicast합니다.

```json
{
  "message_type": "ACK",
  "device_id": "DC:A6:32:12:34:56",
  "ack_for": "ADVERTISE"
}
```

### 3. DETAIL

Sender는 ACK를 보낸 Receiver의 주소로 실제 RTSP 연결정보를 unicast합니다.

```json
{
  "message_type": "DETAIL",
  "device_id": "DC:A6:32:12:34:56",
  "ip": "192.168.0.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

### 4. DETAIL ACK

Receiver는 DETAIL을 정상적으로 수신하면 Sender에 ACK를 반환합니다.

```json
{
  "message_type": "ACK",
  "device_id": "DC:A6:32:12:34:56",
  "ack_for": "DETAIL"
}
```

### 5. RTSP 연결 확인

Receiver는 DETAIL의 정보를 이용해 다음 URI를 구성합니다.

```text
rtsp://192.168.0.10:8554/stream
```

이후 TCP 연결을 생성하고 다음과 같은 RTSP/2.0 요청을 보냅니다.

```text
OPTIONS rtsp://192.168.0.10:8554/stream RTSP/2.0
CSeq: 1

```

서버가 정상적인 RTSP/2.0 `2xx` 응답을 반환하면 연결 가능 상태로 판단합니다.

`OPTIONS` 성공은 실제 영상 재생 성공을 의미하지 않습니다.

## 설치

프로젝트 루트에서 실행합니다.

```powershell
python --version
python -m pip install -e .
```

Python 버전은 다음과 같아야 합니다.

```text
Python 3.11.9
```

## Python API

패키지는 다음 형태로 사용합니다.

```python
from ynb import sender, receiver
```

### Sender

Sender는 한 번의 부트스트랩 교환을 수행합니다.

```python
from ynb import sender

sender.advertise(
    device_id="DC:A6:32:12:34:56",
    ip="192.168.0.10",
    rtsp_port=8554,
    rtsp_path="/stream",
    timeout=5,
)
```

`advertise()`는 다음 흐름을 수행합니다.

```text
ADVERTISE broadcast
        ↓
ADVERTISE ACK 수신
        ↓
DETAIL unicast
        ↓
DETAIL ACK 수신
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

## 패키지 구조

```text
src/ynb/
├── __init__.py
├── sender.py
├── receiver.py
└── connecter.py
```

* `sender.py`: ADVERTISE 송신, ACK 수신, DETAIL 송신
* `receiver.py`: ADVERTISE/DETAIL 수신, ACK 송신, 발견 결과 반환
* `connecter.py`: RTSP URI 생성 및 RTSP/2.0 probe

## 테스트

```powershell
python -m unittest discover -s tests -v
```

최소한 다음 흐름을 검증합니다.

```text
ADVERTISE broadcast
        ↓
ACK unicast
        ↓
DETAIL unicast
        ↓
ACK unicast
        ↓
RTSP/2.0 OPTIONS
        ↓
rtsp_connected
```

## 현재 범위 밖

0.0.1에서는 다음 기능을 제공하지 않습니다.

* UDP 메시지 자동 재전송
* `message_id`
* 중복 및 재정렬 처리
* callback
* 장비 registry
* 비동기 RTSP probe
* RTSP 영상 재생
* 인증 및 암호화
* 다른 subnet 또는 인터넷을 통한 자동 발견

상세 요구사항은 [`SRS.md`](SRS.md)를 참고하십시오.
