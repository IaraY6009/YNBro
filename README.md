# RTSP Bootstrap

동일 IPv4 LAN에서 송신 장비를 UDP 브로드캐스트로 발견하고, 광고된 RTSP/2.0 엔드포인트를 확인한 뒤 연결 정보를 Python 애플리케이션에 전달하는 표준 라이브러리 기반 패키지입니다.

이 패키지는 RTSP 자체의 탐색 규격이 아니라 **RTSP 연결정보 부트스트랩 프로토콜**입니다. 영상 디코딩·재생, 인증·암호화, 다른 서브넷 탐색, mDNS 및 ONVIF는 다루지 않습니다.

## 설치

Python 3.12 이상이 필요합니다.

```console
python -m pip install .
```

개발 중에는 `python -m pip install -e .`로 editable 설치할 수 있습니다. 런타임 외부 의존성은 없습니다.

## 빠른 실행

RTSP 서버가 실행 중인 송신 장비에서 주기 광고를 시작합니다.

```console
rtsp-bootstrap-sender --device-id camera-01 --ip 192.168.0.10 --rtsp-port 8554 --rtsp-path /stream --detail-json '{"model":"demo-camera","location":"lab"}'
```

같은 LAN의 수신 측에서 발견을 시작합니다. RTSP 확인에 성공한 장비는 stdout에 UTF-8 JSON 한 줄로 출력되고 진단 로그는 stderr로 출력됩니다.

```console
rtsp-bootstrap-receiver --port 37020 --rtsp-timeout 2
```

설치 명령 대신 모듈로도 각각 실행할 수 있습니다.

```console
python -m rtsp_bootstrap sender --device-id camera-01 --ip 192.168.0.10 --rtsp-port 8554 --rtsp-path /stream
python -m rtsp_bootstrap receiver --port 37020
```

기본 limited broadcast 주소 `255.255.255.255`가 네트워크에서 차단되면 송신기에 해당 인터페이스의 directed broadcast 주소를 지정합니다.

```console
rtsp-bootstrap-sender ... --broadcast-address 192.168.0.255
```

송수신 장비는 같은 broadcast domain에 있어야 하고, 수신 측에서 광고된 IPv4/RTSP TCP 포트에 접근할 수 있어야 합니다. 호스트 방화벽에서 UDP 37020(기본값)과 사용하는 RTSP TCP 포트를 허용해야 할 수 있습니다. 인증·암호화가 없는 프로토콜이므로 신뢰할 수 있는 LAN에서만 사용하십시오.

## Python에서 사용

콜백은 장비가 RTSP 확인에 성공할 때 호출되며, 이후 `DETAIL` 내용이 실제로 바뀌면 최신 복사본으로 한 번 더 호출될 수 있습니다. 같은 장비가 새 RTSP 엔드포인트를 광고하거나 실패 후 복구되어 다시 확인에 성공해도 호출됩니다. 콜백은 수신 I/O 스레드에서 순서대로 실행되므로 오래 블로킹하지 않아야 하며, 콜백 안에서 `receiver.stop()`을 호출하는 것은 안전합니다.

```python
from rtsp_bootstrap import BootstrapReceiver


def on_device(info: dict[str, object]) -> None:
    print(info["device_id"], info["rtsp_uri"])


receiver = BootstrapReceiver(on_device=on_device, rtsp_timeout=2.0)
try:
    receiver.serve_forever()
finally:
    receiver.stop()
```

일정 시간 동안 발견한 결과를 반환받을 수도 있습니다. 반환 목록에는 해당 `discover()` 호출 구간에 메시지를 받고 RTSP 확인에 성공한 장비만 포함됩니다.

```python
from rtsp_bootstrap import BootstrapReceiver

with BootstrapReceiver() as receiver:
    devices = receiver.discover(timeout=10.0)

for device in devices:
    print(device["rtsp_uri"])
```

송신기도 import하여 독립적으로 실행할 수 있습니다.

```python
from rtsp_bootstrap import BootstrapSender

sender = BootstrapSender(
    device_id="camera-01",
    ip="192.168.0.10",
    rtsp_port=8554,
    rtsp_path="/stream",
    details={"model": "demo-camera"},
)
try:
    sender.serve_forever()
finally:
    sender.stop()
```

`receiver.get_devices()`는 `device_id`를 키로 하는 전체 최신 상태의 복사본을 반환합니다. 여기에는 RTSP 확인 실패 장비도 `rtsp_connected=False`로 남습니다. 콜백과 `discover()`의 장비 dict에는 다음 키가 있습니다.

```python
{
    "protocol_version": "1.0",
    "device_id": "camera-01",
    "message_id": "...",
    "ip": "192.168.0.10",
    "rtsp_port": 8554,
    "rtsp_path": "/stream",
    "rtsp_uri": "rtsp://192.168.0.10:8554/stream",
    "details": {"model": "demo-camera"},
    "rtsp_connected": True,
    "last_seen": 1786745454.0,
}
```

호출자가 내부 상태를 변경하지 못하도록 반환값과 콜백 인자는 깊은 복사본입니다.

RTSP 확인이 DETAIL보다 먼저 끝나면 최초 콜백의 `details`는 `{}`일 수 있습니다. DETAIL 도착 후에는 갱신 콜백 또는 `get_devices()`로 최신 값을 확인할 수 있습니다.

## 프로토콜

모든 데이터그램은 UTF-8 JSON 객체이며 다음 일곱 필드를 공통으로 포함합니다.

```json
{
  "protocol_version": "1.0",
  "message_type": "ADVERTISE",
  "device_id": "unique-device-id",
  "message_id": "unique-message-id",
  "ip": "192.168.0.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

`message_type`은 `ADVERTISE`, `DETAIL`, `ACK` 중 하나입니다. `DETAIL`에는 `details` 객체와 `in_reply_to`가, `ACK`에는 확인 대상 메시지 ID인 `ack_for`가 추가됩니다.

브로드캐스트만으로 송신기가 수신기의 유니캐스트 주소를 알 수 없으므로 실제 교환은 다음과 같습니다.

```text
송신기                         수신기                         RTSP 서버
  |-- ADVERTISE (broadcast) ---->|
  |<-- ACK for ADVERTISE --------|  정보 수신 및 주소 학습
  |                              |-- OPTIONS ... RTSP/2.0 ---->|
  |-- DETAIL (unicast) --------->|
  |<-- ACK for DETAIL -----------|
  |                              |<-- RTSP/2.0 2xx, CSeq: 1 ----|
  |                              |   성공 결과/콜백
```

첫 ACK를 즉시 보내야 송신기가 그 UDP 원주소를 DETAIL 유니캐스트 대상으로 학습할 수 있습니다. 따라서 DETAIL 교환과 RTSP 확인은 서로 독립적으로 진행될 수 있습니다. 두 ACK는 각각 유효하고 현재 교환과 상관된 JSON 정보를 수신·처리했다는 뜻이며, RTSP 영상 재생, SETUP/PLAY, RTP 수신 또는 디코딩 성공을 의미하지 않습니다. 기본 RTSP 확인은 제한시간 안에 광고 URI로 `OPTIONS`를 보내고, 완전한 RTSP/2.0 헤더에서 일치하는 `CSeq: 1`과 2xx 상태를 받았을 때만 성공합니다.

수신기는 `(device_id, message_id)` 중복 캐시를 제한된 크기로 유지합니다. 같은 메시지는 RTSP 확인·상태 반영·콜백을 반복하지 않지만, ACK 유실 복구를 위해 현재 교환에 속하는 중복 ADVERTISE와 DETAIL에는 ACK를 다시 보냅니다. DETAIL은 `in_reply_to`, 엔드포인트, UDP 송신 원주소가 해당 장비의 최신 ADVERTISE와 모두 일치할 때만 반영됩니다. 장비 레지스트리는 `device_id`별 한 항목만 유지하며 유효한 메시지가 마지막으로 도착한 상태를 저장합니다. 성공한 동일 엔드포인트도 새 ADVERTISE가 계속 오면 기본 10초 TTL 뒤 다시 확인합니다.

식별자는 최대 256자, `rtsp_path`는 최대 2048자이며 한 메시지는 IPv4 UDP 최대 payload인 65,507바이트를 넘을 수 없습니다. 잘못된 UTF-8/JSON, 지원하지 않는 버전·타입, 중복·오래된 패킷, RTSP 연결 거부 및 타임아웃은 수신 루프 밖으로 예외를 전파하지 않습니다.

## 테스트

설치 후 표준 라이브러리 `unittest`로 실행합니다.

```console
python -m unittest discover -s tests -v
```

테스트는 실제 외부 장비에 의존하지 않습니다. loopback UDP와 가짜 RTSP/2.0 TCP 서버를 사용해 직렬화·검증, 중복 처리와 재ACK, 타임아웃, 여러 장비, `ADVERTISE → ACK → DETAIL → ACK` 교환과 RTSP 성공 전달 전체 절차를 검증합니다.
