# RTSP 연결정보 부트스트랩 소프트웨어 설계 명세서

## 1. 문서 목적

이 문서는 [`SRS.md`](SRS.md)의 요구사항을 현재 코드가 어떻게 구현하는지
설명한다. 공개 API, module 경계, wire format, 상태 자료구조, thread
모델, 오류 처리와 테스트 구조를 현재 버전 0.1.0 기준으로 고정한다.

## 2. 설계 목표

1.  RTSP 연결정보 발견과 RTSP 자체 연결 확인을 분리한다.
2.  최초 주소를 모르는 상태에서는 broadcast, 주소를 학습한 뒤에는
    unicast를 사용한다.
3.  UDP의 손실·중복·재정렬 특성을 상관 ID와 idempotent 처리로 흡수한다.
4.  느린 RTSP TCP 작업이 UDP listener를 block하지 않게 한다.
5.  외부 입력 오류와 callback 오류가 장기 실행 서비스를 종료시키지 않게
    한다.
6.  표준 라이브러리만으로 재사용 가능한 `ynb` Python package를 제공한다.

## 3. 전체 아키텍처

``` mermaid
flowchart LR
    subgraph SenderProcess[송신 프로세스]
        A[상위 Python 앱]
        S[sender.py]
    end

    subgraph Shared[공통 연결 계층]
        C[connecter.py<br/>검증 + 연결정보 + RTSP/2.0 probe]
    end

    subgraph ReceiverProcess[수신 프로세스]
        R[receiver.py]
        B[상위 Python 앱]
        W[Bounded RTSP workers]
    end

    A --> S
    S --> C
    S <-->|UDP JSON| R
    R --> C
    R --> W
    R -->|device dict| B
```

송신기와 수신기는 같은 process에 있을 필요가 없다. 양쪽이 공유하는 것은
protocol 1.0 JSON 계약뿐이며, Python 객체나 내부 상태를 공유하지 않는다.

## 4. 소스 구성

  -----------------------------------------------------------------------
  파일                    주요 책임               관련 SRS
  ----------------------- ----------------------- -----------------------
  `__init__.py`           `ynb` package 초기화와  FR-API, FR-PKG
                          `sender`, `receiver`    
                          module import 경계      

  `connecter.py`          공통 메시지 검증,       FR-MSG, FR-RTSP
                          연결정보 처리, RTSP URI 
                          및 RTSP/2.0 OPTIONS     
                          probe                   

  `sender.py`             주기 광고, ACK 처리,    FR-SND
                          DETAIL, ACK 대기,       
                          lifecycle               

  `receiver.py`           listener, 장비          FR-RCV
                          registry, 상관 문맥,    
                          probe 조정, callback    
  -----------------------------------------------------------------------

## 5. Wire protocol 설계

### 5.1 메시지 계층

``` text
공통 메시지
├── ADVERTISE
├── DETAIL
│   ├── details: JSON object
│   └── in_reply_to: ADVERTISE.message_id
└── ACK
    └── ack_for: 수신 완료한 message_id
```

`device_id`는 장비의 논리적 identity이고 `message_id`는 개별 전송의
identity다. 같은 장비가 반복 광고할 때 device ID는 유지되고 message ID는
새로 생성된다.

### 5.2 상관관계

  -----------------------------------------------------------------------
  원본                    후속 메시지             검사
  ----------------------- ----------------------- -----------------------
  ADVERTISE `A`           ACK `ack_for=A`         송신 광고 이력과 ACK
                                                  peer

  ADVERTISE `A`           DETAIL `in_reply_to=A`  수신 광고 문맥의
                                                  endpoint, peer, epoch

  DETAIL `D`              ACK `ack_for=D`         pending DETAIL ID와
                                                  최초 전송 peer
  -----------------------------------------------------------------------

ACK는 JSON 정보 수신 완료만 의미한다. RTSP 성공 상태는 ACK 처리로
변경하지 않고 probe 결과로만 변경한다.

### 5.3 전체 시퀀스

``` mermaid
sequenceDiagram
    participant S as BootstrapSender
    participant R as BootstrapReceiver
    participant T as RTSP server
    participant A as Application

    S->>R: ADVERTISE(A, endpoint) broadcast
    R-->>S: ACK(ack_for=A) unicast

    par 상세정보
        S->>R: DETAIL(D, in_reply_to=A) unicast
        R-->>S: ACK(ack_for=D) unicast
    and 연결 확인
        R->>T: OPTIONS URI RTSP/2.0, CSeq: 1
        T-->>R: RTSP/2.0 2xx, CSeq: 1
    end

    R->>A: device snapshot
```

첫 ACK는 송신기가 수신기의 UDP source endpoint를 학습하게 하므로 probe
완료보다 먼저 전송한다.

## 6. Protocol codec 설계

### 6.1 공개 함수

``` text
validate_message(message: Mapping[str, object]) -> dict[str, Any]
make_message(message_type, *, device_id, ip, rtsp_port, rtsp_path,
             message_id=None, **extra) -> dict[str, Any]
encode_message(message: Mapping[str, object]) -> bytes
decode_message(payload: bytes | bytearray | memoryview) -> dict[str, Any]
```

모든 경로는 `validate_message()`를 통과한다. 송신 객체와 수신 객체에
서로 다른 규칙이 생기지 않게 하기 위한 결정이다.

### 6.2 검증 파이프라인

``` mermaid
flowchart TD
    A[bytes-like payload] --> B{1..65507 bytes}
    B -- no --> X[MessageError]
    B -- yes --> C{strict UTF-8}
    C -- no --> X
    C -- yes --> D{JSON object}
    D -- no --> X
    D -- yes --> E{version + message type}
    E -- invalid --> X
    E -- valid --> F{identifier + IPv4 + port + path}
    F -- invalid --> X
    F -- valid --> G{type-specific fields + JSON serializable}
    G -- invalid --> X
    G -- valid --> H[deep-copied normalized dict]
```

JSON encoding은 `ensure_ascii=False`, `allow_nan=False`, compact
separator와 key sorting을 사용한다. 반환 dict는 입력과 분리된 깊은
복사본이다.

## 7. 송신기 설계

### 7.1 공개 인터페이스

``` text
BootstrapSender(
    *,
    device_id: str,
    ip: str,
    rtsp_port: int,
    rtsp_path: str,
    details: Mapping[str, object] | None = None,
    discovery_port: int = 37020,
    broadcast_address: str = "255.255.255.255",
    advertise_interval: float = 2.0,
    bind_host: str = "0.0.0.0",
    bind_port: int = 0,
    on_detail_ack: Callable | None = None,
    history_capacity: int = 4096,
)
```

주요 메서드는 `start()`, `serve_forever()`, `stop()`, `close()`,
`advertise_once()`, `send_detail()`, `wait_for_ack()`,
`get_detail_acks()`다. `local_address`와 `is_running`은 read-only
property다.

### 7.2 내부 상태

  ----------------------------------------------------------------------------------------------
  자료구조                        키와 값                                역할
  ------------------------------- -------------------------------------- -----------------------
  `_advertisements`               advertise ID → `None`                  자신이 발행한 광고 확인

  `_handled_advertisement_acks`   `(advertise ID, peer IP, peer port)`   수신자별 중복 광고 ACK
                                                                         제거

  `_pending_details`              detail ID → peer                       DETAIL ACK peer 검사

  `_detail_acks`                  detail ID → ACK record                 조회·waiter·callback
                                                                         결과

  `_run_generation`               integer                                재시작 경계

  `_cancelled_generation`         integer                                이전 ACK waiter 취소
                                                                         경계
  ----------------------------------------------------------------------------------------------

네 개 이력 map은 bounded `OrderedDict`이며 상한을 넘으면 가장 오래된
항목을 제거한다.

### 7.3 동시성

-   `_state_lock`: 광고·ACK·pending 이력 보호
-   `_lifecycle_lock`: thread, socket, 실행 상태 보호
-   `_ack_condition`: `wait_for_ack()` 대기와 ACK 통지
-   `_stop_event`: 송신 loop와 waiter의 종료 신호
-   `_ready_event`: background bind 성공·실패 알림

UDP 송신 전 history와 pending을 먼저 등록한다. 빠른 LAN에서 `sendto()`
직후 ACK가 돌아와도 known ID로 처리하기 위해서다. `sendto()` 실패 시
등록을 rollback한다.

### 7.4 실행 loop

``` text
bind UDP socket with SO_BROADCAST
send initial ADVERTISE
while not stopped:
    if next interval reached:
        create, remember, broadcast ADVERTISE
    receive datagram with bounded timeout
    if valid correlated ACK:
        process ACK
```

광고 ACK는 `(advertise, peer)`별로 한 번 DETAIL을 만든다. DETAIL ACK는
pending peer와 일치할 때만 record와 callback으로 전달한다.

### 7.5 종료와 재시작

`stop()`은 event를 설정하고 socket을 닫고 ACK condition을 notify한다. 새
`start()`는 이전 thread 종료를 정리한 후 실행 generation을 증가시킨다.
waiter는 ACK 유무뿐 아니라 generation 변경도 조건으로 확인하여 이전
실행에 영구 대기하지 않는다.

## 8. 수신기 설계

### 8.1 공개 인터페이스

``` text
BootstrapReceiver(
    *,
    bind_host: str = "0.0.0.0",
    discovery_port: int = 37020,
    rtsp_timeout: float = 2.0,
    on_device: Callable | None = None,
    rtsp_probe: Callable | None = None,
    max_probe_workers: int = 4,
    max_pending_probes: int = 128,
    probe_success_ttl: float = 10.0,
    dedupe_capacity: int = 4096,
)
```

주요 메서드는 `start()`, `serve_forever()`, `stop()`, `close()`,
`discover()`, `get_devices()`다.

### 8.2 핵심 상태

  --------------------------------------------------------------------------------------------
  자료구조                                               역할
  ------------------------------------------------------ -------------------------------------
  `_devices[device_id]`                                  장비별 최신 snapshot

  `_seen_messages[(device_id, message_id)]`              bounded 중복 이력

  `_latest_advertisements[device_id]`                    최신 `(ID, endpoint, peer, epoch)`

  `_advertisement_contexts[(device_id, advertise_id)]`   과거 광고의 bounded 문맥

  `_device_context_epoch[device_id]`                     endpoint 또는 peer 전환 세대

  `_inflight[device_id]`                                 `(run generation, token, endpoint)`
                                                         probe

  `_last_probe_success[device_id]`                       성공 TTL 계산용 monotonic time

  `_reported_endpoints[device_id]`                       중복 성공 callback 억제

  `_device_seen_sequence[device_id]`                     `discover()` 호출 구간 판정

  `_probe_results`                                       worker → I/O thread 결과 queue
  --------------------------------------------------------------------------------------------

### 8.3 ADVERTISE 처리

``` text
decode and validate
remember duplicate key
register latest device state and advertisement context
send ACK immediately to datagram peer
if new and probe result is not fresh:
    schedule bounded asynchronous probe
```

같은 endpoint면 기존 details와 신선한 성공 상태를 유지한다. endpoint가
바뀌면 details, reported endpoint와 성공 시각을 초기화한다.

### 8.4 DETAIL 문맥 검사

단순히 가장 최신 광고 ID와 같은지만 확인하면 같은 endpoint의 정상적인
UDP 재정렬을 거부한다. 반대로 device ID만 확인하면 과거 endpoint의
DETAIL이 최신 상태를 rollback한다.

장비의 endpoint 또는 UDP peer가 바뀔 때만 context epoch를 증가시킨다.
DETAIL은 다음을 모두 만족해야 한다.

``` text
stored_context(detail.in_reply_to) exists
stored_context.endpoint == detail.endpoint
stored_context.peer == datagram.peer
stored_context.epoch == latest.epoch
latest.endpoint and peer == detail endpoint and peer
current device endpoint == detail endpoint
```

따라서 `A(E) → B(E) → DETAIL(reply=A, E)`는 허용하지만,
`A(OLD) → B(NEW) → DETAIL(reply=A, OLD)`는 거부한다.

### 8.5 비동기 probe

`ThreadPoolExecutor`가 TCP probe를 수행하며 `BoundedSemaphore`가
실행·대기 작업 총량을 제한한다. 같은 장비·endpoint의 inflight 작업은
중복 생성하지 않는다.

worker는 `_devices`를 직접 변경하지 않고 다음 tuple을 result queue에
넣는다.

``` text
(run_generation, device_id, message_token, endpoint, succeeded)
```

I/O thread는 다음 조건을 모두 만족하는 결과만 반영한다.

``` text
result.run_generation == current run_generation
inflight[device_id] == result identity
devices[device_id].endpoint == result.endpoint
```

이 설계는 종료 전 작업, 과거 광고 작업과 변경 전 endpoint 결과가 현재
상태를 덮는 것을 막는다.

### 8.6 callback과 discover

성공 probe는 endpoint가 아직 보고되지 않았을 때 snapshot callback을
발생시킨다. 실패가 적용되면 보고 이력을 지우므로 복구 성공은 다시
callback된다. 연결 상태에서 details가 달라지면 갱신 callback을
발생시킨다.

callback은 lock 밖에서 깊은 복사본으로 호출하고 예외를 catch한다.
callback은 I/O thread에서 직렬 호출되므로 오래 block하면 안 된다.

`discover(timeout)`은 호출 시작의 global message sequence를 저장한 후,
종료 시 그 sequence보다 나중에 유효 메시지를 받은 connected 장비만
반환한다. 누적 registry와 "이번 호출에서 발견한 결과"를 분리하기 위한
설계다.

### 8.7 교착 방지 종료

callback이 I/O thread에서 `stop()`을 호출하거나 주입 probe가 worker에서
`stop()`을 호출할 수 있다. 현재 thread를 join하지 않고, probe worker
문맥에서 시작된 shutdown은 executor 완료 대기를 생략한다. 남은 결과는
generation 검사로 폐기한다.

## 9. RTSP probe 설계

### 9.1 URI

`build_rtsp_uri()`는 검증된 path를 UTF-8 percent-encoding하되 RTSP
URI에서 안전한 구분 문자를 보존한다.

``` text
/영상 → /%EC%98%81%EC%83%81
```

### 9.2 요청

``` text
OPTIONS <uri> RTSP/2.0\r\n
CSeq: 1\r\n
User-Agent: ynb/0.1\r\n
\r\n
```

### 9.3 판정 알고리즘

``` text
deadline = monotonic_now + timeout
TCP connect with remaining time
send request with remaining time
read until CRLF CRLF, deadline or 16384-byte limit
parse ASCII status and headers
return true only if:
    protocol == RTSP/2.0
    200 <= status < 300
    CSeq == 1
```

각 단계에 독립 timeout을 주지 않고 하나의 deadline을 공유하여 전체
실행시간이 설정값을 크게 넘지 않게 한다.

## 10. 장비 snapshot 설계

``` python
{
    "protocol_version": "1.0",
    "device_id": "camera-01",
    "message_id": "...",
    "ip": "192.168.0.10",
    "rtsp_port": 8554,
    "rtsp_path": "/stream",
    "rtsp_uri": "rtsp://192.168.0.10:8554/stream",
    "details": {"model": "demo"},
    "rtsp_connected": True,
    "last_seen": 1786745454.0,
}
```

identity와 endpoint 필드는 DETAIL의 arbitrary keys로 덮지 않고 `details`
아래에 분리한다. 반환·callback마다 deep copy하여 ownership을 호출자에게
넘긴다.

## 11. 패키징 설계

### 11.1 공개 import 형태

사용자가 사용하는 기본 import 계약은 다음과 같다.

``` python
from ynb import sender, receiver
```

`sender.py`와 `receiver.py`가 각각 송신/수신 기능의 공개 module이다.
`connecter.py`는 두 module이 공유하는 내부 연결 계층이다.

### 11.2 소스 배치

``` text
src/ynb/
├── __init__.py
├── connecter.py
├── receiver.py
└── sender.py
```

### 11.3 배포

`setuptools.build_meta`와 `src/` layout을 사용한다. 대상 Python은 정확히
3.11.9이며 runtime dependency는 없다. 패키징 설정은 `pyproject.toml`을
단일 기준으로 사용한다.

## 12. 오류 처리 정책

  -----------------------------------------------------------------------------
  오류 종류               경계                    처리
  ----------------------- ----------------------- -----------------------------
  잘못된 생성자 인자      API 호출                `ValueError` 또는
                                                  `MessageError` 즉시 발생

  잘못된 UDP payload      listener                기록 후 폐기, loop 계속

  UDP timeout             listener                정상 polling 사건

  UDP send 실패           network operation       상태 rollback 또는 종료
                                                  중이면 무시

  RTSP                    probe                   `False`
  timeout·거부·비정상                             
  응답                                            

  callback 예외           callback boundary       logging 후 loop 계속

  bind 실패               startup                 `start()`/foreground/패키지
                                                  통합로 전파

  종료 중 worker 결과     result application      generation mismatch로 폐기
  -----------------------------------------------------------------------------

## 13. 자원 상한과 복잡도

  항목                      설계
  ------------------------- -------------------
  UDP payload               최대 65,507 bytes
  RTSP response header      최대 16,384 bytes
  identifier                최대 256자
  RTSP path                 최대 2,048자
  sender history            기본 4,096 항목
  receiver dedupe/context   기본 4,096 항목
  probe workers             기본 4
  pending probes            기본 128

`B`를 메시지 크기, `D`를 details 크기, `N`을 장비 수라고 할 때 codec은
`O(B)`, 장비·중복·문맥 조회는 평균 `O(1)`, details 복사는 `O(D)`, 전체
snapshot은 `O(N + details 총량)`이다.

장비 registry 자체는 자동 축출하지 않는다. 장기 운용에서 offline device
만료가 필요하면 별도 정책을 설계해야 한다.

## 14. 테스트 설계

``` mermaid
flowchart TD
    U1[test_connecter.py] --> P[connecter.py]
    U2[test_connecter.py] --> T[connecter.py]
    U3[test_sender.py] --> S[sender.py]
    U4[test_receiver.py] --> R[receiver.py]
    E[test_e2e.py] --> S
    E --> R
    E --> F[FakeRtspServer]
    C[test_cli.py] --> 패키지 통합[installed-style module 패키지 통합]
```

`tests/support.py`는 실제 loopback TCP socket을 사용하는
`FakeRtspServer`와 UDP client를 제공한다. receiver 단위 테스트는 probe
dependency injection으로 성공, 실패, timeout과 예외를 결정적으로 만든다.
E2E는 sender·receiver와 fake RTSP server를 실제 UDP/TCP socket으로
연결한다.

주요 회귀 조건은 다음과 같다.

-   중복 메시지는 한 번 처리하되 ACK 재전송
-   오래된 DETAIL의 endpoint rollback 차단
-   같은 endpoint의 정상 재정렬 허용
-   callback/probe 내부 stop의 무교착
-   stop 후 즉시 restart와 과거 waiter 취소
-   ACK와 RTSP 성공 의미 분리
-   호출 구간별 `discover()` 결과

## 15. 설계 결정과 trade-off

  -----------------------------------------------------------------------
  결정                    이점                    비용·제약
  ----------------------- ----------------------- -----------------------
  ADVERTISE ACK를 즉시    수신자 주소 학습,       ACK가 RTSP 성공으로
  전송                    probe와 독립            오해될 수 있어 문서
                                                  필요

  strict RTSP/2.0         요구 버전을 정확히 검증 RTSP/1.0 전용 서버와
                                                  기본 호환되지 않음

  worker pool probe       UDP responsiveness      generation/token 기반
                                                  stale 결과 관리 필요

  bounded history         장기 메모리 증가 제한   매우 오래된 중복은 새
                                                  메시지처럼 처리될 수
                                                  있음

  device registry 무만료  최신 알려진 상태 조회   장기 offline 장비가
                          가능                    자동 삭제되지 않음

  callback on I/O thread  순서 단순화             callback이 짧고
                                                  non-blocking이어야 함

  dict public contract    Python 통합이 단순      정적 타입의 구체성이
                                                  낮음
  -----------------------------------------------------------------------

## 16. 확장 지점

-   `rtsp_probe` 주입: RTSP/1.0, 인증 또는 실제 media 확인 정책을 별도
    구현할 수 있다.
-   `on_device`: message queue, database, UI adapter에 연결할 수 있다.
-   `on_detail_ack`: 송신 장비가 수신 완료 telemetry를 기록할 수 있다.
-   `details`: protocol identity를 변경하지 않고 JSON metadata를 확장할
    수 있다.

인증, 암호화, 다른 subnet relay 또는 wire field 의미 변경은 단순
주입점이 아니라 protocol version과 [`SRS.md`](SRS.md)의 변경이 필요하다.

## 17. 역할별 코드 소유권

  -----------------------------------------------------------------------
  역할                    1차 소유                공동 검토
  ----------------------- ----------------------- -----------------------
  송신부                  `sender.py`,            protocol 상관 ID, E2E
                          `test_sender.py`        

  수신부                  `receiver.py`,          probe 계약, callback,
                          `test_receiver.py`      E2E

  연결부                  `connecter.py`, 대응    sender/receiver wire
                          단위 테스트             사용

  통합·배포               package metadata,       모든 공개 계약
                          public API, E2E, 문서   
  -----------------------------------------------------------------------

wire schema, ACK 의미, callback dict, RTSP 성공 기준과 lifecycle을
변경할 때는 관련 역할의 공동 검토가 필요하다.
