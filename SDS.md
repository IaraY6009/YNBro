# RTSP 연결 정보 부트스트랩 소프트웨어 설계 명세서

## 1. 문서 정보

| 항목 | 내용 |
| --- | --- |
| 문서 이름 | YNB Software Design Specification |
| 대상 버전 | 0.0.1 |
| 구현 언어 | Python 3.11 이상 |
| 기준 검증 환경 | Python 3.11.9 |
| 관련 요구사항 | [`SRS.md`](SRS.md) |
| 구현 현황 | [`SRS_IMPLEMENTATION_REPORT.md`](SRS_IMPLEMENTATION_REPORT.md) |
| 상태 | 구현 기준 문서 |

이 문서는 SRS가 정의한 요구사항을 YNB 0.0.1 코드에서 어떻게 구현했는지
설명한다. SRS가 "무엇을 만족해야 하는가"를 정의한다면, SDS는 모듈의
책임, 상태 전이, 데이터 검증, 오류 의미와 반드시 유지해야 할 불변식을
정의한다.

## 2. 목적과 설계 범위

### 2.1 목적

YNB는 동일한 IPv4 브로드캐스트 도메인에서 Sender의 존재를 발견하고,
Sender가 제공한 RTSP 엔드포인트(endpoint)에 Receiver가 최소 RTSP/2.0
연결 확인을 수행하도록 돕는 부트스트랩 패키지다.

0.0.1은 다음 흐름 한 번을 동기식으로 실행한다.

```text
ADVERTISE broadcast
        ↓
ADVERTISE ACK unicast
        ↓
DETAIL unicast
        ↓
DETAIL ACK unicast
        ↓
TCP connect + RTSP/2.0 OPTIONS
```

### 2.2 설계 범위

이 설계가 다루는 기능은 다음과 같다.

- IPv4 UDP 브로드캐스트를 이용한 일회성 발견
- 실제 UDP 발신 peer를 이용한 상대 고정
- ADVERTISE, ACK, DETAIL 메시지 생성과 엄격한 검증
- RTSP URI 구성과 RTSP/2.0 `OPTIONS` probe
- UDP 교환 실패와 RTSP probe 실패를 구분한 결과 반환
- 전체 호출에 적용되는 단일 timeout 예산

다음 기능은 0.0.1 설계 범위 밖이다.

- UDP 재전송, 중복 제거, 순서 복구
- `message_id`, nonce, replay 방지
- 여러 장비를 누적하는 registry
- 비동기 API 또는 상시 실행 daemon
- IPv6 또는 라우터를 넘는 자동 발견
- RTSP 인증, RTP 수신, 영상 재생
- 메시지 서명, 암호화, 발신자 인증

## 3. 시스템 컨텍스트

### 3.1 실행 주체

| 주체 | 역할 |
| --- | --- |
| Sender | ADVERTISE를 방송하고, ACK를 보낸 Receiver에 RTSP 정보를 전달한다. |
| Receiver | Sender를 한 대 선택하고 DETAIL을 받은 뒤 RTSP probe를 수행한다. |
| RTSP Server | DETAIL에 적힌 IPv4, TCP port, path에서 RTSP/2.0 요청에 응답한다. |

Sender와 RTSP Server는 같은 장비일 수도 있고 서로 다른 장비일 수도 있다.
DETAIL의 `ip`는 UDP Sender의 주소가 아니라 Receiver가 TCP로 접속할 RTSP
Server의 주소다.

### 3.2 네트워크 배치

```text
┌──────────────────────────────┐
│ Sender                       │
│ UDP bind: 0.0.0.0:임시 port │
└──────────────┬───────────────┘
               │ ADVERTISE
               │ 255.255.255.255:37020
               ▼
┌──────────────────────────────┐
│ Receiver                     │
│ UDP bind: 0.0.0.0:37020      │
│                              │
│ ACK/DETAIL은 선택한 peer와   │
│ UDP unicast로 교환           │
└──────────────┬───────────────┘
               │ TCP connect
               │ RTSP/2.0 OPTIONS
               ▼
┌──────────────────────────────┐
│ DETAIL의 ip:rtsp_port        │
│ RTSP Server                  │
└──────────────────────────────┘
```

`255.255.255.255`는 기본 limited broadcast 주소다. 일반적인 라우터는 이
패킷을 다른 subnet으로 전달하지 않는다. `broadcast_address`를 변경할 수
있지만 구현은 IPv4 문법만 검사한다. 지정한 주소가 실제 directed broadcast
주소인지는 호출자가 네트워크 prefix를 바탕으로 확인해야 한다.

### 3.3 주요 용어

| 용어 | 설계에서의 의미 |
| --- | --- |
| peer | `recvfrom()`이 반환한 실제 `(IPv4, UDP port)` 발신 주소 |
| endpoint | Receiver가 RTSP 접속에 사용하는 `(ip, rtsp_port, rtsp_path)` |
| start port | ADVERTISE를 받는 bootstrap UDP port, 기본값 `37020` |
| deadline | 한 호출 전체가 공유하는 단조 시계 기준 절대 마감 시각 |
| probe | TCP 연결 후 RTSP/2.0 OPTIONS의 2xx 응답을 확인하는 작업 |

peer와 endpoint는 서로 다른 개념이다. peer는 UDP 교환 상대이며 endpoint는
그 뒤에 Receiver가 접속할 RTSP 목적지다.

## 4. 모듈 구조

### 4.1 의존 관계

```text
ynb.__init__
 ├── sender ───────────────→ _protocol
 └── receiver ─────────────→ _protocol
      └── connecter ───────→ _protocol
```

모든 런타임 모듈은 Python 표준 라이브러리만 사용한다.

### 4.2 모듈 책임

| 모듈 | 책임 | 책임지지 않는 기능 |
| --- | --- | --- |
| `__init__.py` | `sender`, `receiver` 공개와 버전 제공 | CLI, 상태 관리 |
| `_protocol.py` | 상수, 값 검증, 메시지 생성·파싱, UTF-8 JSON 변환 | socket I/O, peer 선택 |
| `sender.py` | ADVERTISE → ACK → DETAIL → ACK 교환 | RTSP probe, registry, 재전송 |
| `receiver.py` | Sender 선택, ACK, DETAIL 검증, probe 호출, 결과 조립 | 여러 장비 누적, daemon 실행 |
| `connecter.py` | RTSP URI 구성, TCP 연결, OPTIONS 요청과 응답 판정 | DESCRIBE, SETUP, PLAY, RTP |

`connecter.py`의 파일명은 일반적인 영어 철자 `connector`와 다르지만,
SRS의 `FR-API-004`에 지정된 이름이므로 0.0.1에서는 유지한다.

### 4.3 패키징

프로젝트는 `pyproject.toml`과 setuptools build backend를 사용하며 Python
package는 `src/ynb` 아래에 두는 src layout이다. 배포 이름과 import 이름은
모두 `ynb`, version은 `0.0.1`, `requires-python`은 `>=3.11`이다. runtime
dependency 목록은 비어 있으며 build 과정에만 setuptools가 필요하다.

## 5. 핵심 설계 불변식

코드를 수정할 때 다음 조건을 보존해야 한다.

1. ADVERTISE만 브로드캐스트하며 endpoint를 포함하지 않는다.
2. Sender는 두 송신 메시지를 모두 검증한 뒤에만 socket을 연다.
3. 첫 유효 ADVERTISE ACK의 실제 peer가 DETAIL 목적지가 된다.
4. Sender는 같은 peer, 같은 `device_id`, `ack_for="DETAIL"`인 ACK만 인정한다.
5. Receiver도 선택한 peer와 `device_id`가 모두 같은 DETAIL만 인정한다.
6. 정의되지 않은 wire 필드와 잘못된 원격 입력은 거부한다.
7. 잘못된 원격 입력은 전체 Receiver를 종료하지 않고 deadline까지 무시한다.
8. blocking 수신 대기는 단계마다 timeout을 다시 시작하지 않고 남은 deadline을 쓴다.
9. Receiver는 DETAIL ACK를 보낸 뒤 RTSP probe를 시작한다.
10. UDP ACK 성공과 RTSP probe 성공은 서로 다른 결과다.
11. 한 호출은 재전송, background task 또는 registry를 만들지 않는다.

peer 고정은 한 번의 교환에서 상대가 섞이는 것을 막는 일관성 검사다.
암호학적 인증이나 UDP source spoofing 방지는 아니다.

## 6. Wire protocol 설계

### 6.1 전송 규칙

- 한 메시지는 UTF-8 JSON 객체 하나다.
- 한 메시지는 UDP 데이터그램 하나에 완전히 들어가야 한다.
- JSON 최상위 값은 object여야 한다.
- 메시지별 필드 집합은 SRS에 정의된 집합과 정확히 같아야 한다.
- 추가 필드도 다른 protocol 버전과의 우발적 혼용으로 보고 거부한다.
- 송신 JSON은 불필요한 공백 없이 compact 형식으로 직렬화한다.
- 표준 JSON 값이 아닌 `NaN`, `Infinity`는 송수신 모두 거부한다.

### 6.2 메시지 schema

| 메시지 | 정확한 필드 | 전송 방식 |
| --- | --- | --- |
| ADVERTISE | `message_type`, `device_id` | Sender → start port broadcast |
| ADVERTISE ACK | `message_type`, `device_id`, `ack_for` | Receiver → Sender peer unicast |
| DETAIL | `message_type`, `device_id`, `ip`, `rtsp_port`, `rtsp_path` | Sender → ACK peer unicast |
| DETAIL ACK | `message_type`, `device_id`, `ack_for` | Receiver → Sender peer unicast |

`ack_for`는 문자열 `ADVERTISE` 또는 `DETAIL`이다. ACK의 `device_id`는
Receiver의 ID가 아니라 ACK 대상 Sender의 `device_id`다.

### 6.3 필드 검증

| 필드 | 검증 규칙 |
| --- | --- |
| `message_type` | 메시지 parser가 기대하는 정확한 상수 |
| `device_id` | `AA:BB:CC:DD:EE:FF` 형태의 6바이트 MAC 문자열 |
| `ack_for` | `ADVERTISE` 또는 `DETAIL` |
| `ip` | 숫자로 표현한 유효한 IPv4 문자열 |
| `rtsp_port` | `bool`이 아닌 정수 `1..65535` |
| `rtsp_path` | `/`로 시작하며 ASCII C0(U+0000~U+001F)와 DEL(U+007F)이 없는 Unicode 문자열 |
| `timeout` | `bool`이 아닌 0 이상의 유한한 수 |

Python에서 `bool`은 `int`의 하위 타입이므로 port 1 또는 timeout 1초로
잘못 처리되지 않도록 명시적으로 거부한다. `device_id`는 문법만 검사하며
실제 NIC 소유권을 확인하거나 대소문자를 정규화하지 않는다.

### 6.4 송수신 검증 파이프라인

```text
송신 인자
  → make_* 값 검증
  → 정확한 dict 생성
  → encode_message
  → compact UTF-8 JSON
  → 크기 확인
  → sendto

UDP bytes
  → 데이터그램 크기 확인
  → UTF-8 decode
  → JSON object 확인
  → parse_* exact-field 검사
  → 필드별 값 검증
  → 상위 상태 머신
```

`MessageError`는 wire 계약 또는 직렬화 오류를 나타내는 `ValueError`의
하위 타입이다. Receiver와 ACK 대기 루프는 원격 입력에서 발생한
`MessageError`를 호출자에게 전파하지 않고 해당 데이터그램만 무시한다.

### 6.5 크기 제한

IPv4 UDP payload의 이론상 최대 크기는 65,507바이트다. 구현은 수신 시
한 바이트 더 요청해 초과 데이터그램이 정상 크기로 잘려 처리되지 않게 하고,
decoder에서 이를 거부한다. 실제 LAN에서는 훨씬 작은 데이터그램도 IP
fragmentation 때문에 손실될 수 있으므로 이 값은 권장 크기가 아니라
절대 상한이다.

## 7. Sender 상세 설계

### 7.1 공개 함수

```python
sender.advertise(
    device_id,
    ip,
    rtsp_port,
    rtsp_path,
    timeout=5,
    *,
    start_port=37020,
    broadcast_address="255.255.255.255",
    bind_host="0.0.0.0",
    bind_port=0,
) -> bool
```

### 7.2 상태 머신

```text
VALIDATE
   ↓
OPEN_SOCKET
   ↓
BROADCAST_ADVERTISE
   ↓
WAIT_ADVERTISE_ACK
   ↓
UNICAST_DETAIL
   ↓
WAIT_DETAIL_ACK
   ↓
True
```

| 상태 | 동작 | 다음 상태 또는 결과 |
| --- | --- | --- |
| S0 `VALIDATE` | ADVERTISE와 DETAIL 생성, 두 payload 직렬화, timeout과 port 검증 | 잘못된 호출은 `ValueError`/`MessageError`; 성공 시 S1 |
| S1 `OPEN_SOCKET` | IPv4 UDP socket 생성, `SO_BROADCAST=1`, local bind | `OSError`면 `False`; 성공 시 S2 |
| S2 `BROADCAST_ADVERTISE` | `(broadcast_address, start_port)`로 ADVERTISE 전송 | `OSError`면 `False`; 성공 시 S3 |
| S3 `WAIT_ADVERTISE_ACK` | 같은 ID와 `ack_for=ADVERTISE`인 첫 ACK의 실제 peer 선택 | timeout/socket 오류는 `False`; 성공 시 S4 |
| S4 `UNICAST_DETAIL` | 선택한 ACK peer로 DETAIL 전송 | `OSError`면 `False`; 성공 시 S5 |
| S5 `WAIT_DETAIL_ACK` | 같은 peer, ID, `ack_for=DETAIL`인 ACK 대기 | 유효 ACK는 `True`; timeout/socket 오류는 `False` |

형식, `device_id`, `ack_for` 또는 peer가 다른 ACK는 즉시 실패로 처리하지
않고 남은 deadline 동안 무시한다. ADVERTISE ACK를 보낸 port와 start port가
같을 것이라고 추측하지 않으며, 반드시 `recvfrom()`의 실제 peer를 쓴다.

Sender는 broadcast 송신, 두 ACK 수신, DETAIL 송신에 같은 UDP socket을
계속 사용한다. 따라서 한 교환 중 Sender의 source port가 유지된다.

`bind_port=0`은 운영체제가 임시 source port를 고르게 한다는 뜻이다.
고정 방화벽 규칙이 필요하면 호출자가 사용 가능한 port를 지정할 수 있다.

### 7.3 Sender 결과 의미

`True`는 Receiver가 DETAIL ACK를 보냈다는 뜻이다. Receiver의 RTSP probe는
DETAIL ACK 뒤에 실행되므로 Sender의 반환값으로 RTSP 성공을 알 수 없다.

## 8. Receiver 상세 설계

### 8.1 공개 함수

```python
receiver.discover(
    timeout=5,
    *,
    start_port=37020,
    bind_host="0.0.0.0",
) -> dict | None
```

### 8.2 상태 머신

```text
VALIDATE_AND_BIND
        ↓
WAIT_ADVERTISE
        ↓
ACK_AND_PIN_SENDER
        ↓
WAIT_DETAIL
        ↓
ACK_DETAIL
        ↓
PROBE_RTSP
        ↓
RETURN_RESULT
```

| 상태 | 동작 | 다음 상태 또는 결과 |
| --- | --- | --- |
| R0 `VALIDATE_AND_BIND` | 설정 검증, deadline 생성, UDP start port bind | 잘못된 호출은 `ValueError`; socket 오류는 `None` |
| R1 `WAIT_ADVERTISE` | 잘못된 입력을 무시하고 첫 유효 ADVERTISE 선택 | timeout/socket 오류는 `None`; 성공 시 R2 |
| R2 `ACK_AND_PIN_SENDER` | 실제 peer로 ACK 전송, peer와 ID 고정 | `OSError`면 `None`; 성공 시 R3 |
| R3 `WAIT_DETAIL` | 다른 peer, 다른 ID, 잘못된 DETAIL 무시 | timeout/socket 오류는 `None`; 성공 시 R4 |
| R4 `ACK_DETAIL` | 같은 peer로 DETAIL ACK 전송 | `OSError`면 `None`; 성공 시 R5 |
| R5 `PROBE_RTSP` | 전체 deadline의 남은 시간으로 RTSP probe | 성공 여부와 무관하게 R6 |
| R6 `RETURN_RESULT` | endpoint, URI, probe 결과를 dict로 조립 | dict 반환 |

DETAIL ACK를 probe보다 먼저 보내는 이유는 느리거나 실패한 RTSP 서버가
Sender의 ACK 대기를 지연시키지 않게 하기 위해서다.

`discover()`는 호출 한 번에 최초의 유효 Sender 한 대만 처리하고 종료한다.
다른 장비를 찾으려면 함수를 다시 호출해야 한다.

### 8.3 Receiver 결과 schema

```python
{
    "device_id": str,
    "ip": str,
    "rtsp_port": int,
    "rtsp_path": str,
    "rtsp_uri": str,
    "rtsp_connected": bool,
}
```

유효 DETAIL을 받고 DETAIL ACK 송신까지 완료했다면, 이후 RTSP probe가
실패해도 endpoint 정보를 잃지 않고 위 dict를 반환하며
`rtsp_connected`만 `False`로 설정한다. DETAIL ACK 송신 자체가 실패하면
UDP 교환 미완료이므로 `None`이다.

## 9. Timeout 설계

### 9.1 절대 deadline

각 단계마다 동일한 timeout을 새로 부여하면 잘못된 패킷이 들어올 때마다
호출 시간이 계속 늘어날 수 있다. 이를 막기 위해 다음 형태를 사용한다.

```text
deadline = time.monotonic() + timeout
remaining = deadline - time.monotonic()
```

`time.monotonic()`은 운영체제 시각이 변경되어도 경과 시간 계산이 역행하지
않는다.

| 영역 | 공유 범위 |
| --- | --- |
| Sender | 두 ACK 수신 루프가 같은 절대 deadline의 남은 시간을 사용 |
| Receiver | ADVERTISE/DETAIL 수신과 RTSP probe에 남은 예산을 사용 |
| RTSP probe | TCP 연결, 요청 송신, 응답 수신까지 |

deadline은 blocking 네트워크 대기에 대한 soft budget이다. 로컬 socket
생성·bind와 최초 UDP 송신에는 별도 timeout을 설정하지 않으며, UDP ACK
송신도 직전 수신에 설정된 timeout을 사용한다. Receiver는 원래 deadline의
남은 초를 RTSP probe에 넘기고 probe는 그 값으로 자체 deadline을 만든다.
따라서 Python 코드 실행, OS socket 처리와 자원 정리 오버헤드까지 포함하는
엄격한 real-time 상한은 아니다.

유한한 Python float라도 운영체제가 socket timeout으로 표현하지 못할 수
있다. 이때 발생하는 `OverflowError`는 네트워크 대기 실패로 변환하여 Sender는
`False`, Receiver는 `None`, 직접 RTSP probe는 `False`를 반환한다.

### 9.2 timeout 0의 경계 동작

- Sender는 ADVERTISE를 보낸 뒤 ACK 대기를 즉시 실패하여 `False`를 반환한다.
- Receiver는 socket 준비 후 수신하지 않고 `None`을 반환한다.
- RTSP probe는 TCP 연결을 만들지 않고 `False`를 반환한다.

## 10. RTSP probe 설계

### 10.1 URI 구성

`build_rtsp_uri()`는 endpoint를 다시 검증하고 다음 URI를 만든다.

```text
rtsp://<IPv4>:<port><path>
```

path의 한글, 공백 등 URI 요청 행에 직접 쓸 수 없는 문자는 UTF-8 percent
encoding한다. ASCII C0 제어 문자와 DEL은 protocol 검증 단계에서 먼저
거부한다. C1 영역 문자는 현재 허용되며 URI에서 percent encoding된다.

### 10.2 요청

```text
OPTIONS <full-rtsp-uri> RTSP/2.0\r\n
CSeq: 1\r\n
User-Agent: ynb/0.0.1\r\n
\r\n
```

각 RTSP header 행은 CRLF로 끝나며 마지막 빈 행이 header의 끝을 나타낸다.
`CSeq`는 RTSP 요청 순서를 나타내는 필수 header다.

### 10.3 TCP 수신

TCP는 UDP처럼 메시지 경계를 보존하지 않는 byte stream이다. 한 번의
`recv()`로 전체 응답이 온다고 가정하지 않고 `\r\n\r\n`이 나타날 때까지
여러 조각을 합친다.

- response header 최대 크기: 16 KiB
- header 종료 없이 EOF: 실패
- timeout 또는 연결 거부: 실패
- 응답 body: 읽거나 해석하지 않음
- 응답의 `CSeq`: 현재 버전에서는 일치 여부를 검사하지 않음

### 10.4 성공 판정

완전한 header의 첫 줄이 `RTSP/2.0`, 세 자리 status code, 출력 가능한 ASCII
reason phrase를 각각 한 칸으로 구분한 형태이며 status code가 200 이상
300 미만일 때만 성공이다. 제어 문자나 tab 구분자는 허용하지 않는다.

| 응답 예 | 결과 |
| --- | --- |
| `RTSP/2.0 200 OK` | `True` |
| `RTSP/2.0 299 ...` | `True` |
| `RTSP/2.0 401 Unauthorized` | `False` |
| `RTSP/1.0 200 OK` | `False` |
| 불완전하거나 잘못된 status line | `False` |

OPTIONS 성공은 RTSP 제어 endpoint가 최소 요청에 응답했다는 뜻이다.
DESCRIBE, SETUP, PLAY 또는 실제 영상 재생 성공을 보장하지 않는다.

## 11. 공개 반환 및 오류 계약

| 함수 | 성공 | 정상적인 네트워크 실패 | 잘못된 호출 설정 |
| --- | --- | --- | --- |
| `sender.advertise()` | DETAIL ACK 수신 시 `True` | UDP timeout/socket 오류 시 `False` | `ValueError` 또는 `MessageError` |
| `receiver.discover()` | DETAIL 이후 결과 dict | UDP 미완료/socket 오류 시 `None`; RTSP 실패는 dict의 `False` | `ValueError` |
| `build_rtsp_uri()` | URI 문자열 | 해당 없음 | `ValueError` |
| `probe_rtsp()` | RTSP/2.0 2xx이면 `True` | endpoint/연결/응답 실패 시 `False` | 잘못된 timeout은 `ValueError` |

Receiver 결과는 다음 세 의미를 구분한다.

```text
None
  = UDP 발견 또는 DETAIL 교환이 완료되지 않음

dict + rtsp_connected=False
  = UDP 정보 교환은 완료했지만 RTSP probe 실패

dict + rtsp_connected=True
  = UDP 정보 교환과 최소 RTSP/2.0 OPTIONS probe 성공
```

현재 구현은 bind 실패와 ACK 송신 실패도 Sender의 `False` 또는 Receiver의
`None`에 포함한다. 공개 logging과 세분화된 오류 객체는 향후 확장 지점이다.

## 12. 동시성, 수명 주기와 자원

- 공개 함수는 모두 동기식이며 호출 thread를 blocking한다.
- socket은 context manager로 관리하여 정상 및 오류 경로에서 닫는다.
- 전역 registry나 변경 가능한 공유 상태가 없다.
- `discover()` 한 호출은 최대 한 Sender 결과만 반환한다.
- `SO_REUSEADDR`로 로컬 주소 재사용 동작을 요청하지만, 같은 port에 여러
  process가 bind되는 조건과 데이터그램 분배는 운영체제마다 다르다. 이는
  다중 Receiver 지원을 의미하지 않는다.
- 최대 동시 장비 수, queue 또는 background worker 개념은 없다.
- UDP 손실 시 자동 재전송하지 않고 timeout 결과로 종료한다.

## 13. 보안과 신뢰 경계

### 13.1 신뢰 모델

0.0.1은 신뢰할 수 있는 동일 LAN에서의 PoC 사용을 전제한다. 인증, 메시지
서명, 암호화, replay 방지를 제공하지 않는다.

### 13.2 주요 위험

| 위험 | 현재 동작 |
| --- | --- |
| UDP source spoofing | peer를 사용하지만 발신자의 실제 신원을 인증하지 못함 |
| 위조 ACK | nonce나 `message_id`가 없어 같은 형식의 ACK를 위조할 수 있음 |
| 최초 Sender 선점 | 공격자의 유효 ADVERTISE가 Receiver 호출을 먼저 점유할 수 있음 |
| endpoint 유도 | DETAIL 송신자가 Receiver를 임의 IPv4와 port로 TCP 접속시킬 수 있음 |
| 정보 노출 | broadcast ADVERTISE가 MAC 형식 `device_id`를 LAN에 노출함 |
| 평문 통신 | UDP JSON과 `rtsp://`가 암호화되지 않음 |
| 입력 flood | 패킷 개수 제한이 없어 deadline 동안 잘못된 입력 처리에 CPU를 쓸 수 있음 |
| 작은 UDP reflection | 위조한 source 주소의 ADVERTISE/ACK로 제3자에게 작은 응답을 유도할 수 있음 |
| 로컬 port 경쟁 | 다른 process의 bind와 데이터그램 분배가 OS 정책에 따라 달라질 수 있음 |

DETAIL의 endpoint IP가 UDP Sender peer와 같아야 한다는 제한은 없다. 이는
별도 RTSP Server를 광고할 수 있게 하지만, 신뢰하지 못하는 네트워크에서는
내부 port scan 또는 SSRF와 유사한 연결 유도 위험이 된다.

### 13.3 현재 완화책

- 메시지와 endpoint의 엄격한 형식 검증
- RTSP path 제어 문자 차단
- UDP payload와 RTSP header 크기 상한
- blocking 수신과 RTSP 작업에 적용되는 timeout budget
- 한 번 선택한 peer와 `device_id` 고정

이 완화책은 입력 안전성과 자원 사용을 개선하지만 인증을 대신하지 않는다.
실제 배포에서는 신뢰 LAN으로 범위를 제한하고 방화벽에서 필요한 UDP와
RTSP TCP port만 허용해야 한다.

## 14. 시험 설계

### 14.1 자동 시험 계층

| 시험 파일 | 설계 검증 대상 |
| --- | --- |
| `tests/test_protocol.py` | exact schema, 값 경계, UTF-8 JSON, 비정상 입력 |
| `tests/test_sender.py` | broadcast socket 설정, 실제 ACK peer, 위조 ACK 무시 |
| `tests/test_receiver.py` | malformed 입력 생존, peer/ID 고정, ACK와 결과 |
| `tests/test_connecter.py` | URI, OPTIONS/CSeq, 2xx, 연결 거부와 timeout |
| `tests/test_e2e.py` | 공개 API 전체 흐름과 RTSP 성공·실패 결과 |

전체 흐름 시험은 실제 loopback UDP/TCP socket을 사용한다. 기본 broadcast
목적지와 `SO_BROADCAST` 검사는 외부 LAN에 패킷을 보내지 않도록 mock
socket으로 검증한다.

### 14.2 요구사항 추적

| SRS 영역 | 주 구현 | 주 시험 |
| --- | --- | --- |
| CON-006, Wire 5장 | `_protocol.py` | `test_protocol.py` |
| FR-SND-001~007 | `sender.py`, `_protocol.py` | `test_sender.py` |
| FR-RCV-001~008 | `receiver.py`, `_protocol.py` | `test_receiver.py` |
| FR-RTSP-001~007 | `connecter.py` | `test_connecter.py` |
| FR-API-001~004, 결과 9장 | `__init__.py`, 공개 함수 | `test_e2e.py` |
| CON-003~005, E2E | Sender/Receiver socket 흐름 | 구조 시험 + loopback E2E + 실장비 수동 시험 |

실제 broadcast 도달성은 NIC, subnet, 운영체제 방화벽, AP client isolation에
영향을 받으므로 서로 다른 실제 장비를 사용한 통합 시험을 별도로 수행한다.

## 15. 배포와 구성

| 설정 | 기본값 | 설계 의도 |
| --- | --- | --- |
| UDP start port | `37020` | Sender와 Receiver가 반드시 같은 값을 사용 |
| broadcast 주소 | `255.255.255.255` | 현재 IPv4 link의 limited broadcast |
| Sender bind host | `0.0.0.0` | 운영체제가 송신 인터페이스 선택 |
| Sender bind port | `0` | 운영체제가 임시 source port 선택 |
| Receiver bind host | `0.0.0.0` | 모든 로컬 IPv4 인터페이스에서 수신 |
| Sender timeout | `5`초 | 두 ACK 수신 루프가 공유하는 budget |
| Receiver timeout | `5`초 | UDP 수신과 내부 probe의 budget |
| 직접 RTSP probe timeout | `2`초 | TCP 연결·송신·수신 budget |

`bind_host`는 문자열 타입만 사전 검사한다. `localhost`처럼 운영체제가
해석할 수 있는 이름도 socket bind 단계에서 동작할 수 있다. 존재하지 않는
문자열 주소나 hostname의 bind 실패는 Sender의 `False` 또는 Receiver의
`None`으로 변환된다. 실제 LAN 실행에서는 모호함을 피하기 위해 숫자 IPv4를
사용하는 것이 좋다.

다중 NIC 또는 VPN 환경에서는 Sender의 `bind_host`를 실제 LAN IPv4로
고정하고, 해당 subnet mask로 계산한 directed broadcast 주소를 사용할 수
있다. 예를 들어 `/24`라고 확인된 `192.168.1.10/24`의 broadcast는
`192.168.1.255`지만, prefix를 확인하지 않고 마지막 octet을 255로 가정하면
안 된다.

## 16. 설계 제한과 향후 변경 지점

다음 변경은 현재 wire 계약에 조용히 추가해서는 안 된다.

- `protocol_version` 또는 `message_id` 추가
- ACK 상관관계를 UUID 기반으로 변경
- ADVERTISE에 endpoint 추가
- registry, TTL, callback, 비동기 worker 추가
- RTSP/1.0 호환 또는 인증 추가

이 항목들은 기존 0.0.1 peer와 상호 운용되지 않을 수 있다. 차기 SRS에서
protocol versioning, 이전 버전 거부 또는 협상 방식, migration 계획을 먼저
정의한 뒤 구현해야 한다.

## 17. 최종 설계 요약

YNB 0.0.1은 작은 공통 protocol 계층 위에 Sender, Receiver, RTSP probe의
세 동기식 상태 머신을 둔다. 설계의 핵심은 실제 UDP peer 고정, exact wire
schema, 하나의 monotonic deadline, DETAIL ACK와 RTSP 결과의 분리다.

이 구조는 PoC 범위를 작고 시험 가능하게 유지한다. 반면 인증, 재전송,
여러 장비 관리와 실제 스트리밍은 의도적으로 다루지 않으므로, 신뢰할 수
있는 동일 LAN이라는 전제를 벗어나는 배포에서는 추가 설계가 필요하다.
