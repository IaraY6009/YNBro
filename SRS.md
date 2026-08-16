# RTSP 연결정보 부트스트랩 소프트웨어 요구사항 명세서

## 1. 문서 정보

| 항목 | 값 |
| --- | --- |
| 문서명 | Software Requirements Specification |
| 대상 시스템 | `YNB` (`ynb` Python package) |
| 대상 버전 | 0.1.0 |
| protocol version | 1.0 |
| 기준 Python | 3.11.9 |
| 문서 상태 | 현재 구현 기준 |

이 문서에서 "하여야 한다"는 검증 가능한 필수 요구사항을 뜻한다. 설계와
구현 방법은 [`SDS.md`](SDS.md), 사용법과 학습 자료는
[`README.md`](README.md)를 참조한다.

## 2. 목적과 범위

### 2.1 목적

시스템은 동일 IPv4 LAN에 있는 송신 장비를 UDP broadcast로 자동 발견하고,
광고된 RTSP endpoint가 RTSP 2.0 요청에 응답하는지 확인한 뒤, 연결정보를
상위 Python 애플리케이션에 전달하여야 한다.

### 2.2 시스템 성격

이 시스템은 RTSP 자체의 탐색 표준이 아니라 **RTSP 연결정보 부트스트랩
프로토콜**이다. 시스템은 장비의 존재와 RTSP URI를 전달하고 최소 연결
가능성을 확인하지만, 영상 재생은 수행하지 않는다.

### 2.3 범위 제외

-   RTSP `DESCRIBE`, `SETUP`, `PLAY`, `TEARDOWN` 세션 관리
-   RTP/RTCP 수신
-   영상·음성 디코딩과 화면 출력
-   사용자 인증, 메시지 인증, 암호화
-   인터넷 또는 서로 다른 subnet 사이의 자동 발견
-   mDNS, SSDP, ONVIF 탐색
-   장비 상태의 영구 저장
-   사라진 장비의 자동 만료·삭제 정책

## 3. 용어

| 용어 | 정의 |
| --- | --- |
| 송신기 | 자신의 RTSP 연결정보를 광고하는 `Sender` 측 |
| 수신기 | 광고를 받고 RTSP를 확인하는 `Receiver` 측 |
| start port | UDP 발견 메시지를 주고받는 포트. 기본값은 37020 |
| RTSP port | 광고된 RTSP TCP 서버 포트 |
| endpoint | `(ip, rtsp_port, rtsp_path)` 튜플 |
| peer | UDP 데이터그램의 실제 발신 `(ip, port)` |
| 장비 | 동일 `device_id`로 식별되는 논리적 송신 장비 |
| probe | 광고 endpoint로 보내는 RTSP/2.0 `OPTIONS` 확인 |
| ACK | 유효하고 현재 교환에 속하는 JSON 정보의 수신 확인 |
| callback | RTSP 성공 또는 연결 후 상세정보 변경을 상위 앱에 통지하는 함수 |
**  -----------------------------------------------------------------------**

## 4. 시스템 환경과 제약

### 4.1 실행 환경

-   Python 3.11.9
-   IPv4를 사용하는 동일 broadcast domain
-   UDP broadcast와 unicast가 허용되는 LAN
-   광고된 RTSP TCP endpoint에 수신기에서 접근 가능한 환경

### 4.2 기술 제약

| ID | 요구사항 |
| --- | --- |
| CON-001 | 패키지는 `pyproject.toml` 기반으로 빌드되어야 한다. |
| CON-002 | runtime 기능은 Python 표준 라이브러리만 사용하여야 한다. |
| CON-003 | wire 데이터는 한 UDP 데이터그램에 담긴 UTF-8 JSON 객체여야 한다. |
| CON-004 | 최초 발견은 UDP broadcast, 응답과 DETAIL은 UDP unicast를 사용하여야 한다. |
| CON-005 | 자동 발견 범위는 IPv4 동일 LAN으로 제한하여야 한다. |
| CON-006 | 기본 RTSP 검사는 RTSP 2.0을 대상으로 하여야 한다. |
**  -----------------------------------------------------------------------**

## 5. 시스템 컨텍스트

``` mermaid
flowchart LR
    D[송신 장비]
    S[Sender]
    R[Receiver]
    T[RTSP 서버]
    A[상위 Python 애플리케이션]

    D --> S
    S <-->|UDP ADVERTISE / ACK / DETAIL| R
    R -->|TCP RTSP/2.0 OPTIONS| T
    R -->|검증된 연결정보 dict| A
```

송신 장비와 RTSP 서버는 같은 장비에서 실행될 수 있지만 논리적으로 다른
역할이다. `Sender`는 RTSP 서버를 생성하지 않는다.

## 6. Wire 데이터 요구사항

### 6.1 공통 필드

모든 메시지는 다음 필드를 포함하여야 한다.

| 필드 | 타입 | 제약 |
|---|---|---|
| `protocol_version` | string | 정확히 `1.0` |
| `message_type` | string | `ADVERTISE`, `DETAIL`, `ACK` 중 하나 |
| `device_id` | string | 공백이 아닌 UTF-8 문자열, 최대 256자 |
| `message_id` | string | 메시지별 고유 식별자, 최대 256자 |
| `ip` | string | 유효한 IPv4 주소 |
| `rtsp_port` | integer | `1..65535`, `bool` 제외 |
| `rtsp_path` | string | `/`로 시작, 최대 2048자, 공백·제어문자 제외 |

한 메시지의 UTF-8 payload는 65,507바이트를 초과하지 않아야 한다.

### 6.2 유형별 필드

| 메시지 | 추가 필드 | 의미 |
| --- | --- | --- |
| `ADVERTISE` | 없음 | 장비와 endpoint 광고 |
| `DETAIL` | `details`, `in_reply_to` | 추가 JSON 객체와 원인 ADVERTISE ID |
| `ACK` | `ack_for` | 확인 대상 메시지 ID |
**  -----------------------------------------------------------------------**

`details`의 전체 값은 유한한 숫자만 포함하는 JSON 객체여야 한다. `NaN`,
`Infinity`, 순환 객체, JSON이 아닌 Python 객체와 lone Unicode
surrogate는 허용하지 않는다.

### 6.3 메시지 예시

``` json
{
  "protocol_version": "1.0",
  "message_type": "ADVERTISE",
  "device_id": "camera-01",
  "message_id": "advertise-uuid",
  "ip": "192.168.0.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

## 7. 기능 요구사항

### 7.1 메시지 처리

| ID | 요구사항 |
| --- | --- |
| FR-MSG-001 | 시스템은 유효한 메시지를 compact UTF-8 JSON bytes로 직렬화하여야 한다. |
| FR-MSG-002 | 시스템은 UDP payload를 엄격한 UTF-8과 JSON 객체로 역직렬화하여야 한다. |
| FR-MSG-003 | 송신 전에 생성 메시지에도 수신 메시지와 동일한 schema 검증을 적용하여야 한다. |
| FR-MSG-004 | 잘못된 버전, 유형, 필드, endpoint 또는 JSON 값을 네트워크 상태에 반영하지 않아야 한다. |
| FR-MSG-005 | 잘못된 네트워크 입력은 listener 밖으로 예외를 전파하지 않아야 한다. |
| FR-MSG-006 | 메시지 ID를 지정하지 않으면 고유 ID를 생성하여야 한다. |

### 7.2 송신기

| ID | 요구사항 |
| --- | --- |
| FR-SND-001 | 송신기는 시작 직후 ADVERTISE를 한 번 broadcast하여야 한다. |
| FR-SND-002 | 송신기는 설정된 양의 주기로 새로운 ADVERTISE를 반복하여야 한다. |
| FR-SND-003 | 송신기는 ADVERTISE ACK의 UDP 발신 주소를 수신기 unicast 주소로 학습하여야 한다. |
| FR-SND-004 | 유효한 ADVERTISE ACK를 최초 처리할 때 해당 peer로 DETAIL을 unicast하여야 한다. |
| FR-SND-005 | DETAIL의 \`in\_reply\_to\`는 원인 ADVERTISE의 \`message\_id\`여야 한다. |
| FR-SND-006 | DETAIL ACK는 실제 pending DETAIL ID와 전송 peer가 모두 일치할 때만 수락하여야 한다. |
| FR-SND-007 | 같은 수신자의 중복 ADVERTISE ACK가 중복 DETAIL 처리를 만들지 않아야 한다. |
| FR-SND-008 | 다른 수신자의 ACK는 같은 ADVERTISE에 대해서도 독립적으로 처리하여야 한다. |
| FR-SND-009 | 호출자는 DETAIL ACK를 callback, 조회 또는 대기 결과로 확인할 수 있어야 한다. |
| FR-SND-010 | 종료 또는 재시작 시 이전 실행의 무기한 ACK 대기자를 해제하여야 한다. |
| FR-SND-011 | 잘못된 endpoint나 비-JSON details는 network thread 시작 전에 거부하여야 한다. |

### 7.3 수신기

| ID | 요구사항 |
| --- | --- |
| FR-RCV-001 | 수신기는 설정된 UDP 주소와 포트에서 ADVERTISE와 DETAIL을 수신하여야 한다. |
| FR-RCV-002 | 수신기는 \`device\_id\`별로 하나의 최신 장비 상태를 유지하여야 한다. |
| FR-RCV-003 | 유효한 ADVERTISE를 등록한 직후 RTSP 결과와 독립적으로 ACK를 peer에 전송하여야 한다. |
| FR-RCV-004 | 수신기는 새롭고 재검증이 필요한 ADVERTISE에 대해 RTSP probe를 예약하여야 한다. |
| FR-RCV-005 | 같은 \`(device\_id, message\_id)\`의 상태 반영과 callback을 중복 수행하지 않아야 한다. |
| FR-RCV-006 | ACK 유실 복구를 위해 허용된 중복 ADVERTISE와 DETAIL에는 ACK를 다시 전송하여야 한다. |
| FR-RCV-007 | DETAIL의 \`in\_reply\_to\`, endpoint, peer와 광고 문맥이 현재 장비 문맥과 일치할 때만 반영하여야 한다. |
| FR-RCV-008 | 과거 endpoint의 늦은 DETAIL이 최신 endpoint를 덮지 못하게 하여야 한다. |
| FR-RCV-009 | 같은 endpoint와 peer의 연속 광고 사이에서 재정렬된 DETAIL은 광고 문맥이 보존된 동안 허용하여야 한다. |
| FR-RCV-010 | endpoint가 변경되면 이전 details와 RTSP 성공 이력을 새 endpoint에 적용하지 않아야 한다. |
| FR-RCV-011 | probe 실패 장비도 전체 상태에는 \`rtsp\_connected=false\`로 보존하여야 한다. |
| FR-RCV-012 | probe 성공 장비만 발견 성공 결과와 최초 callback으로 전달하여야 한다. |
| FR-RCV-013 | 연결된 장비의 details가 실제로 바뀌면 최신 snapshot으로 callback을 다시 호출하여야 한다. |
| FR-RCV-014 | callback에는 내부 상태와 분리된 깊은 복사본을 전달하여야 한다. |
| FR-RCV-015 | callback 예외가 listener를 종료시키지 않아야 한다. |
| FR-RCV-016 | \`discover(timeout)\`은 해당 호출 구간에 관찰되고 RTSP 성공인 장비만 반환하여야 한다. |
| FR-RCV-017 | \`get\_devices()\`는 \`device\_id\`를 키로 한 전체 최신 상태의 깊은 복사본을 반환하여야 한다. |

### 7.4 RTSP 연결 확인

| ID | 요구사항 |
| --- | --- |
| FR-RTSP-001 | 시스템은 endpoint를 \`rtsp\://\<ip>:\<port>\<encoded-path>\` URI로 구성하여야 한다. |
| FR-RTSP-002 | 비 ASCII path는 UTF-8 percent-encoding하여야 한다. |
| FR-RTSP-003 | 기본 probe는 광고 URI로 \`OPTIONS ... RTSP/2.0\`을 전송하여야 한다. |
| FR-RTSP-004 | TCP 연결, 송신과 응답 수신은 하나의 전체 timeout 안에서 끝나야 한다. |
| FR-RTSP-005 | 완전한 \`CRLF CRLF\` 응답 header를 받아야 성공 판정을 수행하여야 한다. |
| FR-RTSP-006 | 정확한 \`RTSP/2.0\` status line, \`2xx\`, \`CSeq: 1\`을 모두 만족할 때만 성공하여야 한다. |
| FR-RTSP-007 | RTSP 응답 header는 최대 16,384바이트까지만 읽어야 한다. |
| FR-RTSP-008 | timeout, 연결 거부와 잘못된 응답은 예외 대신 \`false\` 결과로 처리하여야 한다. |
| FR-RTSP-009 | 수신기는 동일 성공 endpoint도 설정된 성공 TTL 이후 새 광고에서 재검증하여야 한다. |

### 7.5 공개 Python API

| ID | 요구사항 |
| --- | --- |
| FR-API-001 | 패키지는 \`from ynb import sender, receiver\` 형태의 import를 지원하여야 한다. |
| FR-API-002 | 송신기와 수신기는 독립적으로 \`start()\`, \`serve\_forever()\`, \`stop()\`할 수 있어야 한다. |
| FR-API-003 | 두 객체는 context manager를 지원하여야 한다. |
| FR-API-004 | receiver는 callback 방식과 \`discover()\` 반환 방식 모두 지원하여야 한다. |
| FR-API-005 | receiver는 \`(ip, port, path, timeout) -> bool\` 형태의 probe 주입을 지원하여야 한다. |
| FR-API-006 | 시작 시 bind 실패는 호출자에게 오류로 전달하여야 한다. |
| FR-API-007 | \`local\_address\`와 \`is\_running\`을 읽기 전용 상태로 제공하여야 한다. |
| FR-API-008 | 공통 연결정보 처리와 RTSP probe 구현은 \`connecter\` 모듈에 배치하고 sender/receiver가 이를 재사용하여야 한다. |

### 7.6 패키지 사용

| ID | 요구사항 |
| --- | --- |
| FR-PKG-001 | 사용자는 \`from ynb import sender, receiver\`로 두 기능 모듈을 import할 수 있어야 한다. |
| FR-PKG-002 | \`sender.py\`는 송신 측 공개 기능을 제공하여야 한다. |
| FR-PKG-003 | \`receiver.py\`는 수신 측 공개 기능을 제공하여야 한다. |
| FR-PKG-004 | \`connecter.py\`는 송수신 양측이 공유하는 연결정보 검증 및 RTSP/2.0 확인 책임을 가져야 한다. |
| FR-PKG-005 | 패키지는 Python 3.11.9에서 설치 및 실행 가능하여야 하며 다른 Python 버전은 지원 대상으로 간주하지 않는다. |

## 8. 장비 결과 데이터 요구사항

수신기의 장비 snapshot은 다음 값을 제공하여야 한다.

| 키 | 타입 | 설명 |
| --- | --- | --- |
| \`protocol\_version\` | string | wire protocol version |
| \`device\_id\` | string | 장비 상태 키 |
| \`message\_id\` | string | 마지막 반영 메시지 ID |
| \`ip\` | string | 광고된 IPv4 |
| \`rtsp\_port\` | integer | 광고된 RTSP port |
| \`rtsp\_path\` | string | 광고된 RTSP path |
| \`rtsp\_uri\` | string | 조합·인코딩된 URI |
| \`details\` | object | 최신 허용 DETAIL 객체 |
| \`rtsp\_connected\` | boolean | 마지막 적용 probe 결과 |
| \`last\_seen\` | number | 마지막 유효 메시지의 Unix timestamp |

**## 9. 비기능 요구사항 **

### 9.1 신뢰성과 오류 내성

| ID | 요구사항 |
| --- | --- |
| NFR-REL-001 | 잘못된 UTF-8, JSON, 버전, 메시지와 RTSP timeout이 장기 실행 listener를 종료시키지 않아야 한다. |
| NFR-REL-002 | callback 또는 주입 probe의 예외가 서비스 전체를 종료시키지 않아야 한다. |
| NFR-REL-003 | callback 또는 probe 내부에서 receiver 종료를 요청해도 교착이 발생하지 않아야 한다. |
| NFR-REL-004 | 종료 직후 재시작해도 이전 실행의 thread와 비동기 결과가 새 상태를 오염시키지 않아야 한다. |

### 9.2 자원과 성능

| ID | 요구사항 |
| --- | --- |
| NFR-PERF-001 | RTSP probe는 UDP 수신과 ACK 전송을 block하지 않아야 한다. |
| NFR-PERF-002 | probe worker 수와 pending 작업 수에 설정 가능한 상한을 두어야 한다. |
| NFR-PERF-003 | dedupe, 광고 문맥, ACK와 pending 이력에 설정 가능한 상한을 두어야 한다. |
| NFR-PERF-004 | 정상적인 상태 조회와 중복 판정은 평균 상수 시간 자료구조를 사용하여야 한다. |

### 9.3 보안과 운영

| ID | 요구사항 |
| --- | --- |
| NFR-SEC-001 | network 입력은 사용 전에 schema와 크기를 검증하여야 한다. |
| NFR-SEC-002 | 문서는 인증·암호화가 없음을 명시하고 신뢰 LAN에서만 사용하도록 안내하여야 한다. |
| NFR-SEC-003 | 반환 snapshot을 수정해 내부 상태를 변경할 수 없어야 한다. |

### 9.4 배포성과 유지보수성

| ID | 요구사항 |
| --- | --- |
| NFR-PKG-001 | wheel은 \`py3-none-any\` 순수 Python package로 빌드 가능하여야 한다. |
| NFR-PKG-002 | wheel에는 \`ynb\` 패키지의 \`\_\_init\_\_.py\`, \`sender.py\`, \`receiver.py\`, \`connecter.py\`와 license가 포함되어야 한다. |
| NFR-PKG-003 | runtime dependency를 추가하지 않아야 한다. |
| NFR-MNT-001 | sender, receiver와 공통 연결 계층(connecter)의 책임은 독립 module로 분리하여야 한다. |
| NFR-MNT-002 | 자동 테스트는 외부 카메라 없이 loopback에서 반복 실행 가능하여야 한다. |

**  -----------------------------------------------------------------------**

## 10. 주요 시나리오

### 10.1 정상 발견

``` text
송신기  -> ADVERTISE broadcast
수신기  -> ADVERTISE ACK unicast
송신기  -> DETAIL unicast
수신기  -> DETAIL ACK unicast
수신기  -> RTSP/2.0 OPTIONS
RTSP   -> RTSP/2.0 2xx, CSeq: 1
수신기  -> 상위 앱에 device dict
```

DETAIL 교환과 RTSP probe는 서로 독립적으로 진행될 수 있다.

### 10.2 RTSP 실패

수신기는 유효한 ADVERTISE와 DETAIL을 상태에 저장하고 ACK하지만, 장비를
성공 callback 또는 `discover()` 결과에 포함하지 않아야 한다.
`get_devices()`에서는 `rtsp_connected=false`로 확인할 수 있어야 한다.

### 10.3 중복과 재정렬

중복 메시지는 상태와 callback을 반복하지 않지만 ACK는 재전송한다. 같은
endpoint·peer 문맥의 지연 DETAIL은 허용할 수 있고, 이전 endpoint 문맥의
DETAIL은 ACK 없이 폐기하여야 한다.

## 11. 검증과 추적성

| 요구 영역 | 자동 검증 |
| --- | --- |
| wire schema, UTF-8, JSON, 경계값 | `tests/test_protocol.py` |
| RTSP/2.0 OPTIONS와 URI | `tests/test_rtsp.py` |
| sender 설정, ACK waiter, 재시작 | `tests/test_sender.py` |
| receiver 상태, 중복, 재정렬, callback, probe | `tests/test_receiver.py` |
| 실제 loopback UDP/TCP 전체 흐름 | `tests/test_e2e.py` |
| package import와 공개 module | import smoke test 및 관련 단위 테스트 |
| VirtualBox와 외부 RTSP 환경 | README의 실제 블랙박스 테스트 절 |
**  -----------------------------------------------------------------------**

자동 완료 기준은 다음과 같다.

``` console
python -m unittest discover -s tests -v
```

모든 자동 테스트가 통과하고, 실제 배포 전 동일 LAN 환경에서 broadcast
발견과 RTSP 접근성을 별도로 확인하여야 한다.

## 12. 알려진 제한과 변경 절차

-   현재 protocol version은 `1.0`만 허용한다.
-   기본 probe는 RTSP/1.0 서버를 성공으로 인정하지 않는다.
-   장비 registry는 자동 만료되지 않는다.
-   callback은 수신 I/O thread에서 호출되므로 오래 block하면 안 된다.
-   보안 또는 subnet 간 발견이 필요하면 현재 protocol의 단순 옵션 추가가
    아니라 별도 요구사항과 위협 모델이 필요하다.

wire 필드, ACK 의미, RTSP 성공 판정 또는 장비 dict 계약을 변경할 때는 이
문서의 관련 요구사항, [`SDS.md`](SDS.md), README와 단위·통합 테스트를
함께 갱신하여야 한다.
