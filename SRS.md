# RTSP 연결정보 부트스트랩 소프트웨어 요구사항 명세서

## 1. 문서 정보

| 항목        | 값                                   |
| --------- | ----------------------------------- |
| 문서명       | Software Requirements Specification |
| 대상 시스템    | `YNB` (`ynb` Python package)        |
| 대상 버전     | 0.0.1                               |
| 기준 Python | 3.11.9                              |
| 대상 RTSP   | RTSP 2.0                            |
| 문서 상태     | 최소 기능 PoC 요구사항                      |

이 문서에서 "하여야 한다"는 검증 가능한 필수 요구사항을 뜻한다.

## 2. 목적과 범위

### 2.1 목적

시스템은 동일 IPv4 LAN에 있는 송신 장비가 광고하는 RTSP 연결정보를 UDP broadcast로 수신하고, 해당 RTSP endpoint가 RTSP 2.0 요청에 응답하는지 확인한 뒤, 결과를 Python `dict`로 제공하여야 한다.

### 2.2 시스템 성격

이 시스템은 RTSP 서버나 RTSP 재생기를 구현하지 않는다.

0.0.1 버전의 목적은 다음 최소 흐름이 실제 환경에서 동작하는지 검증하는 것이다.

```text
Sender
  |
  | UDP broadcast
  | RTSP 연결정보
  v
Receiver
  |
  | TCP connection
  | RTSP/2.0 OPTIONS
  v
RTSP Server
  |
  v
Receiver가 결과 dict 반환
```

### 2.3 범위 제외

0.0.1에서는 다음 기능을 구현하지 않는다.

* `ACK`
* `DETAIL`
* `message_id`
* 메시지 재전송
* 중복 메시지 제거
* UDP 패킷 재정렬 처리
* 장비 상태 registry
* callback
* 성공 TTL
* 비동기 RTSP probe
* worker thread 또는 thread pool
* context manager
* 장비 자동 만료 또는 삭제
* 사용자 인증, 메시지 인증 및 암호화
* RTSP `DESCRIBE`, `SETUP`, `PLAY`, `TEARDOWN`
* RTP/RTCP 수신
* 영상·음성 디코딩 및 재생
* 인터넷 또는 서로 다른 subnet 사이의 자동 발견
* mDNS, SSDP, ONVIF 탐색

## 3. 용어

| 용어         | 정의                                                     |
| ---------- | ------------------------------------------------------ |
| Sender     | 자신의 RTSP 연결정보를 UDP broadcast로 광고하는 측                   |
| Receiver   | 광고를 수신하고 RTSP 연결 가능 여부를 확인하는 측                         |
| device ID  | 송신 장비를 식별하는 값. 0.0.1에서는 네트워크 인터페이스의 MAC 주소를 사용         |
| endpoint   | `(ip, rtsp_port, rtsp_path)`로 구성되는 RTSP 접속정보           |
| probe      | 광고된 endpoint에 RTSP/2.0 `OPTIONS` 요청을 보내 응답 여부를 확인하는 작업 |
| start port | UDP 광고를 송수신하는 포트. 기본값은 `37020`                         |

## 4. 실행 환경과 제약

| ID      | 요구사항                                            |
| ------- | ----------------------------------------------- |
| CON-001 | 시스템은 Python 3.11.9에서 설치 및 실행 가능하여야 한다.          |
| CON-002 | runtime 기능은 Python 표준 라이브러리만 사용하여야 한다.          |
| CON-003 | 자동 발견은 IPv4 동일 broadcast domain에서 수행하여야 한다.     |
| CON-004 | 최초 연결정보 전달은 UDP broadcast를 사용하여야 한다.            |
| CON-005 | wire 데이터는 하나의 UDP 데이터그램에 담긴 UTF-8 JSON 객체여야 한다. |
| CON-006 | RTSP 확인은 RTSP 2.0을 대상으로 하여야 한다.                 |

## 5. Wire 데이터 요구사항

### 5.1 ADVERTISE 메시지

0.0.1에서는 `ADVERTISE` 메시지 한 종류만 사용한다.

메시지는 다음 필드를 포함하여야 한다.

| 필드          | 타입      | 설명                         |
| ----------- | ------- | -------------------------- |
| `device_id` | string  | 송신 장비 네트워크 인터페이스의 MAC 주소   |
| `ip`        | string  | RTSP 서버의 IPv4 주소           |
| `rtsp_port` | integer | RTSP 서버 TCP 포트, `1..65535` |
| `rtsp_path` | string  | `/`로 시작하는 RTSP 경로          |

`device_id`는 `AA:BB:CC:DD:EE:FF` 형태의 MAC 주소 문자열을 사용한다.

메시지 예시는 다음과 같다.

```json
{
  "device_id": "DC:A6:32:12:34:56",
  "ip": "192.168.0.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

## 6. 기능 요구사항

### 6.1 Sender

| ID         | 요구사항                                                                                      |
| ---------- | ----------------------------------------------------------------------------------------- |
| FR-SND-001 | Sender는 MAC 주소를 `device_id`로 사용하고, `ip`, `rtsp_port`, `rtsp_path`와 함께 JSON 메시지를 생성하여야 한다. |
| FR-SND-002 | Sender는 생성한 메시지를 UTF-8 bytes로 직렬화하여야 한다.                                                  |
| FR-SND-003 | Sender는 메시지를 설정된 UDP start port로 broadcast하여야 한다.                                         |
| FR-SND-004 | 잘못된 MAC 주소, IPv4 주소, RTSP port 또는 RTSP path는 전송 전에 거부하여야 한다.                              |

### 6.2 Receiver

| ID         | 요구사항                                                              |
| ---------- | ----------------------------------------------------------------- |
| FR-RCV-001 | Receiver는 설정된 UDP start port에서 ADVERTISE 메시지를 수신하여야 한다.           |
| FR-RCV-002 | Receiver는 수신한 UDP payload를 UTF-8 JSON 객체로 역직렬화하여야 한다.             |
| FR-RCV-003 | Receiver는 필수 필드와 MAC 주소 및 endpoint 값이 유효한지 확인하여야 한다.              |
| FR-RCV-004 | 유효한 메시지를 수신하면 광고된 endpoint에 RTSP probe를 수행하여야 한다.                 |
| FR-RCV-005 | `discover(timeout)`은 지정된 시간 안에 유효한 광고를 수신하지 못하면 결과 없음으로 종료하여야 한다. |
| FR-RCV-006 | 잘못된 UDP 입력은 Receiver 전체를 종료시키지 않아야 한다.                            |

### 6.3 RTSP probe

| ID          | 요구사항                                                             |
| ----------- | ---------------------------------------------------------------- |
| FR-RTSP-001 | 시스템은 endpoint를 `rtsp://<ip>:<port><path>` 형태의 URI로 구성하여야 한다.     |
| FR-RTSP-002 | probe는 광고된 IP와 RTSP port로 TCP 연결을 시도하여야 한다.                      |
| FR-RTSP-003 | TCP 연결 성공 후 광고된 URI에 `OPTIONS ... RTSP/2.0` 요청을 전송하여야 한다.        |
| FR-RTSP-004 | 요청에는 `CSeq` header를 포함하여야 한다.                                    |
| FR-RTSP-005 | 응답 status line이 `RTSP/2.0`이고 상태 코드가 `2xx`이면 probe 성공으로 판단하여야 한다. |
| FR-RTSP-006 | timeout, 연결 거부 또는 잘못된 RTSP 응답은 probe 실패로 처리하여야 한다.               |
| FR-RTSP-007 | RTSP probe 실패는 처리되지 않은 예외로 Receiver 외부에 전파되지 않아야 한다.             |

### 6.4 공개 Python API

| ID         | 요구사항                                                                                |
| ---------- | ----------------------------------------------------------------------------------- |
| FR-API-001 | 패키지는 `from ynb import sender, receiver` 형태의 import를 지원하여야 한다.                       |
| FR-API-002 | `sender.py`는 최소 한 번의 UDP 광고를 수행하는 공개 기능을 제공하여야 한다.                                  |
| FR-API-003 | `receiver.py`는 `discover(timeout)` 형태의 발견 기능을 제공하여야 한다.                             |
| FR-API-004 | 공통 RTSP URI 생성 및 probe 기능은 `connecter.py`에 배치하여 sender 또는 receiver에서 재사용할 수 있어야 한다. |

## 7. 결과 데이터 요구사항

Receiver가 유효한 광고를 수신한 경우 다음 형태의 Python `dict`를 반환하여야 한다.

| 키                | 타입      | 설명                |
| ---------------- | ------- | ----------------- |
| `device_id`      | string  | 광고된 송신 장비의 MAC 주소 |
| `ip`             | string  | 광고된 IPv4 주소       |
| `rtsp_port`      | integer | 광고된 RTSP port     |
| `rtsp_path`      | string  | 광고된 RTSP path     |
| `rtsp_uri`       | string  | 조합된 RTSP URI      |
| `rtsp_connected` | boolean | RTSP probe 결과     |

예:

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

## 8. 최소 테스트 요구사항

### 8.1 UDP 송수신 테스트

Sender가 전송한 ADVERTISE 메시지를 Receiver가 수신하고 다음 값이 동일한지 확인하여야 한다.

* `device_id`
* `ip`
* `rtsp_port`
* `rtsp_path`

`device_id`는 송신 시 사용한 MAC 주소와 동일하여야 한다.

### 8.2 RTSP probe 테스트

loopback TCP 서버가 다음과 같은 RTSP 응답을 반환하도록 구성하여 probe 성공 여부를 확인하여야 한다.

```text
RTSP/2.0 200 OK
CSeq: 1

```

probe 결과는 `True`여야 한다.

연결 거부 또는 timeout 환경에서 probe 결과는 `False`여야 한다.

### 8.3 End-to-End 테스트

다음 전체 흐름을 하나의 테스트에서 검증하여야 한다.

```text
Sender
  |
  | UDP ADVERTISE
  v
Receiver
  |
  | RTSP/2.0 OPTIONS
  v
Fake RTSP Server
  |
  | RTSP/2.0 200 OK
  v
Receiver
  |
  v
rtsp_connected = True
```

## 9. 완료 기준

0.0.1 버전은 다음 조건을 모두 만족하면 완료된 것으로 간주한다.

1. Python 3.11.9에서 패키지를 import할 수 있다.
2. Sender가 MAC 주소와 RTSP 연결정보를 UDP broadcast로 전송할 수 있다.
3. Receiver가 해당 정보를 수신할 수 있다.
4. Receiver가 광고된 endpoint에 RTSP/2.0 `OPTIONS` 요청을 보낼 수 있다.
5. 정상 RTSP 응답에서 `rtsp_connected=True`를 반환할 수 있다.
6. 연결 실패 또는 잘못된 응답에서 `rtsp_connected=False`를 반환할 수 있다.
7. 최소 UDP, RTSP probe, End-to-End 테스트가 통과한다.

## 10. 알려진 제한

* UDP 데이터그램의 전달 성공을 보장하지 않는다.
* 메시지 중복 및 순서 변경을 처리하지 않는다.
* 하나의 장비에 대한 장기 상태를 유지하지 않는다.
* MAC 주소는 네트워크 인터페이스 변경 또는 MAC 주소 변경 시 달라질 수 있다.
* RTSP `OPTIONS` 성공은 실제 영상 재생 성공을 보장하지 않는다.
* 보안 기능을 제공하지 않으므로 신뢰할 수 있는 로컬 네트워크에서 사용하는 것을 전제로 한다.
