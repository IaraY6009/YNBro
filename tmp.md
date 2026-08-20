# `jinwoo`·`receiver` 브랜치 병합 설명

## 1. 한눈에 보는 결론

두 브랜치는 현재 `dev`의 SRS와 다른 시기에, 서로 다른 메시지 규격으로
개발되었습니다. 그래서 원본 파일을 그대로 섞지 않고 다음 원칙으로
`77bfd30` 병합 커밋에서 선별하여 다시 배치했습니다.

1. 실제로 구현되어 있던 UDP 송수신 기법은 가져왔습니다.
2. 메시지 이름과 필드는 `dev`의 SRS 형식으로 고쳤습니다.
3. SRS 범위를 넘어선 기능은 가져오지 않았습니다.
4. 당시 두 브랜치에 없던 기능은 병합 과정에서 완성하지 않았습니다.

병합 커밋은 다음 세 부모를 가지므로 Git 이력상 두 기능 브랜치가 모두
병합되어 있습니다.

- 당시 `dev`: `a1d898c`
- `jinwoo`: `16e75f5`
- `receiver`: `d16afeb`

결과 코드는 별도
`rtsp_discovery` 패키지가 아니라 SRS가 지정한 `src/ynb`에 들어갔습니다.

```text
jinwoo의 UDP 광고 기법 ──┐
                         ├─ SRS 형식으로 교정 ─> src/ynb
receiver의 UDP 수신 기법 ┘
```

## 2. SRS가 요구하는 최종 메시지 흐름

병합 전 두 브랜치는 서로 통신할 수 없는 메시지를 사용했습니다. 통합 코드는
다음 하나의 wire schema를 공유하며, 아래 흐름은 병합 당시 미구현이던
후반부까지 이번 후속 작업으로 완성한 최종 상태입니다.

```text
Sender                         Receiver                    RTSP Server
  |                               |                            |
  |-- ADVERTISE(id=A) broadcast ->|                            |
  |<- ACK(id=A) unicast ----------|                            |
  |-- DETAIL(id=D) unicast ------>|                            |
  |<- ACK(id=D) unicast ----------|                            |
  |                               |-- TCP + OPTIONS ---------->|
  |                               |<- RTSP/2.0 응답 ------------|
```

`message_id`는 canonical lowercase UUID v4이며 ACK는 새 ID를 만들지 않고
확인 대상 메시지의 ID를 그대로 복사합니다.

## 3. `jinwoo` 브랜치에서 가져온 부분

### 원래 구현

`jinwoo`는 Receiver 역할의 client가 discovery request를 broadcast하고,
Sender 역할의 responder가 IP·port·MAC·packet number를 응답하는 구조였습니다.
즉 UDP 광고에 필요한 저수준 동작은 있었지만 SRS가 요구하는 송신 방향과
메시지 순서는 반대였습니다.

### 가져온 구현 기법

- IPv4 UDP socket 생성
- `SO_BROADCAST`를 사용한 broadcast
- `sendto()`와 `recvfrom()` 기반 데이터그램 교환
- `recvfrom()`이 반환한 실제 peer 주소 사용
- `time.monotonic()` 기반 전체 timeout 계산
- UTF-8 JSON encode/decode
- 잘못된 응답을 무시하고 다음 데이터그램을 기다리는 수신 loop
- ACK peer에 endpoint 정보를 unicast하는 동작의 기반

### SRS에 맞게 고친 부분

| 원래 형태 | 병합 후 형태 |
| --- | --- |
| `rtsp_discovery_request/response` | `ADVERTISE/ACK/DETAIL` |
| `type` | `message_type` |
| `packet_number` | UUID v4 `message_id` |
| `mac` | `device_id` |
| `port` | `rtsp_port` |
| Receiver가 먼저 request broadcast | Sender가 먼저 ADVERTISE broadcast |
| 응답 주소를 결과에만 기록 | ACK의 실제 peer를 DETAIL 목적지로 사용 |
| 별도 `rtsp_discovery` API | `ynb.sender.advertise()` |

### 가져오지 않은 범위 초과 기능

- `packet_number` 증가와 순서 관리
- protocol `version`
- request/response 전용 메시지 종류
- 여러 장치 결과 목록과 `DiscoveryResult`
- `seen` 집합을 이용한 중복 제거
- `serve_forever()`, `Event`, `stop()`
- IP와 MAC 자동 추론
- 기존 예제와 자체 request/response 테스트

이 항목들은 SRS 0.0.1에 없거나 명시적으로 범위에서 제외되어 있습니다.

## 4. `receiver` 브랜치에서 가져온 부분

### 원래 구현

`receiver`는 UDP port에서 계속 실행되는 객체로 ADVERTISE와 DETAIL을 받고
ACK를 보내는 기능을 가지고 있었습니다. 다만 `type/version/message_id/status`
등 당시 자체 schema를 사용했고 ADVERTISE와 DETAIL의 endpoint 필드 배치도
현재 SRS와 달랐습니다.

### 가져온 구현 기법

- IPv4 UDP port bind와 `recvfrom()` 수신
- malformed UTF-8/JSON/메시지를 받아도 수신 loop 유지
- 패킷 내부 주소가 아닌 실제 source peer로 ACK unicast
- ADVERTISE 후 DETAIL을 기다리는 단계적 처리
- ACK 송신과 socket 오류 격리
- 수신 endpoint를 RTSP URI로 조합하는 아이디어

### SRS에 맞게 고친 부분

| 원래 형태 | 병합 후 형태 |
| --- | --- |
| `type`, `version` | 정확한 `message_type`만 사용 |
| ADVERTISE에 endpoint 포함 | ADVERTISE에는 `message_id`, `device_id`만 포함 |
| DETAIL에 `stream_path`만 필수 | DETAIL에 IP·port·`rtsp_path` 전체 포함 |
| ACK가 새 UUID 생성 | 대상 메시지의 `message_id`를 ACK에 복사 |
| `in_reply_to`, `receiver_id`, `status` | `device_id`, `ack_for` |
| 임의 DETAIL 수용 | ACK한 정확한 peer와 device의 DETAIL만 수용 |
| `ReceivedDevice` 목록 | SRS의 일회성 `discover(timeout)` 흐름 |
| `rtsp_url` property | `ynb.connecter.build_rtsp_uri()` |

### 가져오지 않은 범위 초과 기능

- `serve_forever()`와 수동 `stop()` lifecycle
- `duplicate_ttl`과 중복 메시지 cache
- 장비 registry와 `get_devices()`
- `receiver_id`와 ACK 처리 상태
- 장비별 장기 상태 보관
- 별도 `rtsp_discovery` 패키지와 깨진 실행 예제

## 5. 공통 protocol에서 교정한 검증

두 브랜치가 각각 느슨하게 검사하던 값을 `src/ynb/_protocol.py` 한 곳에서
검사하도록 통합했습니다.

- 정확한 필드 집합만 허용
- `AA:BB:CC:DD:EE:FF` 형식의 대문자 MAC
- canonical IPv4
- `bool`을 제외한 `1..65535` 정수 port
- `/`로 시작하고 제어 문자나 잘못된 UTF-8 surrogate가 없는 RTSP path
- canonical lowercase UUID v4 `message_id`
- UTF-8 JSON 객체와 UDP payload 크기 제한
- ADVERTISE와 DETAIL에 서로 다른 ID 사용

## 6. 파일별 역할

| 파일 | 역할 | 주된 출처 |
| --- | --- | --- |
| `src/ynb/_protocol.py` | wire 생성·해석·검증 | 두 브랜치의 protocol 코드를 SRS에 맞게 통합 |
| `src/ynb/sender.py` | broadcast, ACK 수신, DETAIL unicast | 주로 `jinwoo`의 UDP client/server 기법 |
| `src/ynb/receiver.py` | ADVERTISE/DETAIL 수신과 ACK | 주로 `receiver`의 수신 loop와 peer ACK |
| `src/ynb/connecter.py` | RTSP URI 생성과 probe | receiver의 URL 조합 아이디어 및 후속 구현 |
| `src/ynb/__init__.py` | `sender`, `receiver` 공개 | SRS 공개 API에 맞춘 배치 |

## 7. 병합 당시 남아 있던 미구현과 후속 구현

`77bfd30` 병합 시점에는 “미구현은 그대로 둔다”는 원칙에 따라 다음 기능이
남아 있었습니다.

- Sender의 DETAIL ACK 수신과 성공 판정
- TCP 연결 및 RTSP/2.0 `OPTIONS` probe
- Receiver의 `rtsp_connected` 판정과 최종 결과 `dict`

```text
77bfd30 당시 Sender: ADVERTISE → ACK → DETAIL → (DETAIL ACK 미수신)
77bfd30 당시 Receiver: ADVERTISE ACK → DETAIL ACK → (probe 없이 None)
```

이후 사용자 요청에 따라 위 항목을 구현했습니다. 새로 추가한 구현 블록은
소스에서 `CODEX-GENERATED` 주석으로 구분되어 있어 기존 두 브랜치에서 가져온
코드와 후속 생성 코드를 쉽게 식별할 수 있습니다.
