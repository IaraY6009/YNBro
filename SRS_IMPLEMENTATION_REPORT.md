# YNB 0.0.1 SRS 구현 현황 보고서

작성 기준일: 2026-08-19  
대상 명세: [`SRS.md`](SRS.md)  
대상 패키지: `src/ynb`

## 1. 결론

현재 코드는 SRS에 정의된 제약 요구사항 7개와 기능 요구사항 26개에
대응하는 실행 경로를 모두 구현했다. 공개 API는 다음 두 함수이다.

```python
from ynb import receiver, sender

sender.advertise(...)
receiver.discover(timeout=5)
```

자동 테스트는 프로토콜, Sender, Receiver, RTSP probe와 전체 교환을
검사한다. 실제 LAN에 패킷을 보내지 않고도 기본 ADVERTISE가
`255.255.255.255:37020`으로 향하고 `SO_BROADCAST`가 설정되는지 구조적으로
검사한다. 전체 교환 테스트는 반복 가능하도록 loopback을 사용한다.

따라서 소프트웨어 구현은 SRS 0.0.1 범위에 도달했다. 다만 서로 다른 실제
장비 사이의 broadcast 도달 여부는 운영체제 방화벽, NIC, AP의 client
isolation과 네트워크 구성에 좌우되므로 별도 통합 시험이 남아 있다.

## 2. 구현 원칙

### 2.1 SRS 0.0.1 wire 계약 유지

wire 메시지는 `ADVERTISE`, `ACK`, `DETAIL` 세 종류만 사용하며, 각 메시지는
SRS에 적힌 필드와 정확히 같은 필드 집합만 허용한다.

| 메시지 | 허용 필드 |
| --- | --- |
| `ADVERTISE` | `message_type`, `device_id` |
| `ACK` | `message_type`, `device_id`, `ack_for` |
| `DETAIL` | `message_type`, `device_id`, `ip`, `rtsp_port`, `rtsp_path` |

과거 검토 대상에 있던 다음 설계는 0.0.1 SRS와 호환되지 않아 병합하지
않았다.

- 모든 메시지에 `protocol_version`, `message_id`, endpoint를 넣는 방식
- ACK의 `ack_for`에 원본 UUID를 넣는 방식
- ADVERTISE 수신 직후 DETAIL 없이 RTSP probe를 시작하는 방식
- `rtsp_bootstrap` 또는 `rtsp_discovery`라는 별도 공개 API
- 장비 registry, TTL, callback, 비동기 worker

이 기능들은 필요하다면 0.0.1 구현에 몰래 섞지 말고, wire 버전을 올리고
호환 정책을 정한 뒤 추가해야 한다.

### 2.2 실제 UDP peer 사용

주소 신뢰의 기준은 JSON 안의 값이 아니라 `recvfrom()`이 반환한 실제
`(IPv4 주소, UDP port)`이다.

```text
Sender -- ADVERTISE --> Receiver
Sender <-- ACK -------- Receiver의 실제 ACK 송신 peer
Sender -- DETAIL -----> 위 ACK peer
```

Sender는 첫 ACK의 실제 peer로 DETAIL을 보내고, DETAIL ACK도 같은 peer에서
온 경우에만 인정한다. Receiver 역시 ADVERTISE를 보낸 실제 peer와
`device_id`를 고정한 뒤, 둘 다 같은 DETAIL만 처리한다. 이 규칙은 동시에
여러 장비가 통신할 때 서로 다른 장비의 메시지가 한 교환 안에서 섞이는
것을 막는다. 다만 인증이나 발신자 위조 방지는 제공하지 않는다.

### 2.3 하나의 절대 timeout

Sender와 Receiver는 한 호출 안에서 단계별 timeout을 새로 시작하지 않는다.
`time.monotonic()`으로 절대 마감 시각을 한 번 계산하고, 매 수신과 RTSP
probe에 남은 시간만 전달한다. 따라서 잘못된 UDP 데이터그램이 계속
들어와도 호출 전체의 실행 시간이 무한히 늘어나지 않는다.

### 2.4 UDP ACK와 RTSP 성공의 분리

`sender.advertise()`의 `True`는 Receiver가 DETAIL을 받고 ACK했다는 뜻이다.
그 뒤 Receiver가 수행하는 RTSP probe 성공을 의미하지 않는다.

`receiver.discover()`는 DETAIL 교환을 마쳤다면 RTSP 연결에 실패하더라도
endpoint 전체를 담은 dict를 반환하고 `rtsp_connected`만 `False`로 둔다.
UDP 교환 자체가 끝나지 않았거나 수신 socket을 사용할 수 없으면 `None`을
반환한다.

## 3. 제약 요구사항 추적

| ID | 상태 | 구현 근거 |
| --- | --- | --- |
| CON-001 | 구현 | `requires-python = ">=3.11"`; Python 3.11 문법 호환성 및 설치 시험 |
| CON-002 | 구현 | runtime 코드는 `socket`, `time`, `json`, `ipaddress`, `re`, `urllib` 등 표준 라이브러리만 사용 |
| CON-003 | 구현 | IPv4 `AF_INET` UDP socket과 limited/directed broadcast 주소 사용 |
| CON-004 | 구현 | Sender가 `SO_BROADCAST=1`을 설정하고 기본 `255.255.255.255:37020`으로 ADVERTISE 전송 |
| CON-005 | 구현 | ACK는 `recvfrom()`의 peer, DETAIL은 ACK peer로 `sendto()`하여 unicast |
| CON-006 | 구현 | 한 메시지를 UTF-8 JSON 객체 하나로 직렬화하여 UDP 데이터그램 하나에 전송 |
| CON-007 | 구현 | TCP 연결 뒤 `OPTIONS ... RTSP/2.0` 요청 및 RTSP/2.0 응답 판정 |

`CON-003`과 `CON-004`의 코드 경로와 socket 설정은 자동 검증되지만, 실제
broadcast domain의 두 장비를 이용한 도달성은 환경 의존 수동 시험이다.

## 4. 기능 요구사항 추적

### 4.1 Sender

| ID | 상태 | 구현 근거 |
| --- | --- | --- |
| FR-SND-001 | 구현 | `_protocol.make_advertisement()`가 최소 ADVERTISE 생성 |
| FR-SND-002 | 구현 | `sender.advertise()`가 설정된 start port로 broadcast |
| FR-SND-003 | 구현 | `_wait_for_ack()`가 절대 deadline까지 유효 ACK 수신 |
| FR-SND-004 | 구현 | `recvfrom()`의 ACK peer를 반환하여 다음 단계 주소로 고정 |
| FR-SND-005 | 구현 | 검증된 4개 DETAIL 값을 ACK peer로 unicast |
| FR-SND-006 | 구현 | 같은 peer의 `ack_for="DETAIL"` ACK만 성공 처리 |
| FR-SND-007 | 구현 | MAC, IPv4, port, path와 모든 payload를 socket 생성 전에 검증 |

Sender는 잘못된 형식의 ACK, 다른 `device_id`, 다른 `ack_for`, 다른 peer의
DETAIL ACK를 무시한다. UDP timeout이나 socket 오류가 발생하면 처리되지
않은 네트워크 예외 대신 `False`를 반환한다.

### 4.2 Receiver

| ID | 상태 | 구현 근거 |
| --- | --- | --- |
| FR-RCV-001 | 구현 | `receiver.discover()`가 설정된 IPv4 UDP port에 bind |
| FR-RCV-002 | 구현 | 유효 ADVERTISE의 실제 peer로 ADVERTISE ACK 전송 |
| FR-RCV-003 | 구현 | ACK를 보낸 peer와 같은 peer의 DETAIL만 수락 |
| FR-RCV-004 | 구현 | exact field, MAC, IPv4, port, path를 공통 parser로 검증 |
| FR-RCV-005 | 구현 | 유효 DETAIL의 실제 peer로 DETAIL ACK 전송 |
| FR-RCV-006 | 구현 | DETAIL ACK 전송을 마친 다음 남은 시간으로 RTSP probe 수행 |
| FR-RCV-007 | 구현 | 공통 deadline 안에 교환이 끝나지 않으면 `None` 반환 |
| FR-RCV-008 | 구현 | 잘못된 UTF-8, JSON, 필드와 메시지 종류를 무시하고 다음 데이터그램 수신 |

한 번의 `discover()` 호출은 SRS의 일회성 동기 흐름에 맞추어 최초의 유효
Sender 한 대만 처리한다. 여러 장비를 누적하는 registry는 구현하지 않았다.

### 4.3 RTSP probe

| ID | 상태 | 구현 근거 |
| --- | --- | --- |
| FR-RTSP-001 | 구현 | `connecter.build_rtsp_uri()`가 endpoint를 검증하고 URI 구성 |
| FR-RTSP-002 | 구현 | `socket.create_connection((ip, port))`로 TCP 연결 |
| FR-RTSP-003 | 구현 | 해당 URI에 ASCII `OPTIONS ... RTSP/2.0` 요청 전송 |
| FR-RTSP-004 | 구현 | 요청에 `CSeq: 1` 포함 |
| FR-RTSP-005 | 구현 | 완전한 header의 첫 줄이 RTSP/2.0이며 200~299일 때만 `True` |
| FR-RTSP-006 | 구현 | timeout, 연결 거부, 불완전 header, 다른 protocol, 비-2xx를 `False`로 처리 |
| FR-RTSP-007 | 구현 | 예상 가능한 socket/인코딩 오류를 probe 안에서 흡수하여 `False` 반환 |

TCP는 메시지 경계가 없는 byte stream이므로 한 번의 `recv()`로 응답 전체가
온다고 가정하지 않는다. `\r\n\r\n`까지 조각을 합치며, 종료 없는 응답으로
메모리를 계속 소비하지 않도록 header 크기를 16 KiB로 제한한다.

### 4.4 공개 API

| ID | 상태 | 구현 근거 |
| --- | --- | --- |
| FR-API-001 | 구현 | `ynb.__init__`이 `sender`, `receiver` module을 공개 |
| FR-API-002 | 구현 | `sender.advertise()`가 전체 UDP 교환 수행 |
| FR-API-003 | 구현 | `receiver.discover(timeout)` 제공 |
| FR-API-004 | 구현 | URI 생성과 probe를 `connecter.py`에 분리 |

## 5. 입력 검증과 방어 동작

공통 protocol module은 다음 입력을 네트워크 사용 전에 거부한다.

- `AA:BB:CC:DD:EE:FF` 형태가 아닌 `device_id`
- IPv6, hostname, 범위를 벗어난 IPv4 주소
- `1..65535` 범위가 아니거나 `bool`인 목적지 port
- `/`로 시작하지 않거나 CR, LF, DEL 등 제어 문자가 있는 RTSP path
- 음수, NaN, 무한대, `bool`인 timeout
- 비어 있거나 UTF-8이 아니거나 최상위 값이 객체가 아닌 JSON
- NaN/Infinity와 초과 필드가 있는 wire 메시지
- IPv4 UDP payload 최대치 65,507 byte를 넘는 직렬화 결과

Python에서 `bool`은 `int`의 하위 타입이므로 별도로 거부한다. 그렇지 않으면
`True`가 port 1 또는 timeout 1초로 조용히 해석될 수 있다.

## 6. 테스트 요구사항 대응

| SRS 절 | 자동 시험 | 판정 |
| --- | --- | --- |
| 10.1 ADVERTISE / ACK | 기본 broadcast 주소와 `SO_BROADCAST`, ADVERTISE exact fields, 실제 ACK peer와 다른 discovery port 사용 | 코드 수준 충족; 실제 LAN 도달성은 수동 확인 필요 |
| 10.2 DETAIL / ACK | 4개 DETAIL 값, 전체 ACK 객체, peer/device 고정, 다른 peer ACK 무시 | 충족 |
| 10.3 RTSP probe | RTSP/2.0 2xx, CSeq, RTSP/1.0 거부, 연결 거부, 응답 timeout | 충족 |
| 10.4 End-to-End | 공개 API로 UDP 전체 교환 후 OPTIONS, 성공 dict와 실패 dict 검사 | 논리 흐름 충족; 자동 시험은 loopback 사용 |

테스트 파일의 역할은 다음과 같다.

| 파일 | 검증 내용 |
| --- | --- |
| `tests/test_protocol.py` | exact wire schema, UTF-8 JSON, 입력 경계와 잘못된 입력 |
| `tests/test_sender.py` | broadcast socket 설정, 실제 ACK peer 사용, 잘못된 ACK 무시 |
| `tests/test_receiver.py` | malformed 입력 생존, peer/device 고정, ACK와 결과 |
| `tests/test_connecter.py` | URI, OPTIONS/CSeq, 2xx, 잘못된 응답과 timeout |
| `tests/test_e2e.py` | 공개 API 전체 성공 흐름과 RTSP 실패 결과 |

### 6.1 2026-08-19 검증 실행 기록

Python 3.11.9 환경에서 다음 검증을 실행했다.

| 검증 | 결과 |
| --- | --- |
| `python -B -m unittest discover -s tests -v` | 22개 테스트, 22개 통과 |
| Python 3.11 AST parsing | source와 test 12개 파일 모두 통과 |
| `git diff --check` | whitespace 오류 없음 |
| wheel build | `ynb-0.0.1-py3-none-any.whl` 생성 성공 |
| 격리 디렉터리 wheel 설치 | 성공 |
| 설치본 `from ynb import sender, receiver` | 성공 |

테스트 실행 시 `PYTHONDONTWRITEBYTECODE=1`을 사용했으며, wheel은 별도 임시
디렉터리에 설치해 source tree가 우연히 import되는 상황을 배제했다.

## 7. 완료 기준 판정

| SRS 11장 완료 기준 | 판정 | 비고 |
| --- | --- | --- |
| 1. Python 3.11.9 import | 충족 | source 및 설치된 wheel import 시험 |
| 2. 최소 ADVERTISE broadcast | 충족 | exact payload, 기본 목적지, socket option 자동 시험 |
| 3. Receiver ADVERTISE 수신 및 ACK unicast | 충족 | 실제 peer 대상 검증 |
| 4. Sender가 ACK peer로 DETAIL unicast | 충족 | ACK 송신 port와 start port를 다르게 하여 검증 |
| 5. Receiver DETAIL 수신 및 ACK unicast | 충족 | 전체 ACK 내용과 peer 검증 |
| 6. RTSP/2.0 OPTIONS 전송 | 충족 | 가짜 TCP 서버가 요청 행과 CSeq 확인 |
| 7. `rtsp_connected` 결과 | 충족 | `True`와 `False` 전체 결과 dict 검증 |
| 8. 최소 End-to-End 테스트 | 충족 | loopback 자동 시험; 실제 LAN은 아래 수동 시험 권고 |

## 8. 남은 실장비 통합 시험

자동 시험은 외부 LAN에 임의 broadcast를 보내지 않는다. 배포 전에 같은
broadcast domain의 서로 다른 두 장비에서 다음 사항을 확인해야 한다.

1. Receiver 장비의 UDP 37020 inbound 방화벽 규칙을 확인한다.
2. Receiver에서 `receiver.discover(timeout=10)`을 먼저 실행한다.
3. Sender에서 기본 `sender.advertise(...)`를 실행한다.
4. Wi-Fi AP의 client isolation이 꺼져 있고 양쪽 subnet mask가 같은지 확인한다.
5. Sender가 `True`, Receiver가 6개 필드의 dict를 반환하는지 확인한다.
6. RTSP 서버가 2xx이면 `rtsp_connected=True`, timeout 또는 비-2xx이면
   같은 endpoint dict와 함께 `False`가 되는지 확인한다.

limited broadcast가 운영체제나 NIC 정책으로 차단되면 해당 subnet의
directed broadcast 주소를 `broadcast_address`로 지정해 시험할 수 있다.

## 9. 남은 제한과 위험

- UDP 특성상 전달과 ACK 수신을 보장하지 않으며 0.0.1은 자동 재전송하지 않는다.
- socket 생성, bind, 송수신 오류는 현재 Sender의 `False` 또는 Receiver의
  `None`으로 합쳐진다. 상세 진단 오류 모델과 logging은 다음 버전 과제다.
- 인증, 서명, 암호화가 없으므로 신뢰할 수 있는 동일 LAN만 전제한다.
- Receiver는 수신한 DETAIL의 endpoint로 TCP 연결을 시도한다. 신뢰할 수
  없는 네트워크에서는 임의 내부 주소 probe를 유도하는 데 악용될 수 있다.
- `OPTIONS` 2xx는 RTSP 제어 endpoint 응답만 뜻하며 영상 재생을 보장하지 않는다.
- registry, 재전송, 중복 제거, 순서 복구, `message_id`는 SRS 범위 밖이다.

## 10. 최종 판정

SRS 0.0.1이 요구하는 코드 경로와 자동화 가능한 최소 시험은 구현되었다.
현재 남은 항목은 새 기능 구현이 아니라, 목표 배포 환경의 두 실제 장비를
사용한 broadcast 통합 확인이다. wire 계약을 변경하는 기능은 0.0.1에
추가하지 말고 차기 SRS에서 versioning과 상호운용 정책부터 정의해야 한다.
