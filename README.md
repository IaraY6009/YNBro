# YNB

YNB는 동일한 IPv4 LAN에서 RTSP 장비의 존재를 UDP 브로드캐스트로 알리고,
Receiver가 전달받은 엔드포인트에 RTSP/2.0 `OPTIONS` 요청을 보내 응답 여부를
확인하는 Python 패키지입니다.

현재 버전은 **0.0.1 PoC**입니다.

- **Sender**: 자신의 존재와 RTSP 연결 정보를 광고하는 측
- **Receiver**: 광고를 받고 전달된 RTSP 엔드포인트를 확인하는 측

PoC는 설계 가능성을 검증하는 초기 구현을 뜻합니다.

> YNB는 별도의 CLI 프로그램이나 상시 실행 daemon을 제공하지 않습니다.
> `sender.advertise()`와 `receiver.discover()` Python API를 직접 호출합니다.
> Receiver를 먼저 실행한 뒤 Sender를 실행해야 합니다.

## 문서 바로가기

- [설치](#2-설치)
- [가장 빠른 로컬 확인](#3-가장-빠른-로컬-확인)
- [한 컴퓨터에서 수동 실행](#4-한-컴퓨터에서-수동-loopback-실행)
- [두 컴퓨터에서 실제 LAN 실행](#5-두-컴퓨터에서-실제-lan-실행)
- [방화벽 설정](#6-방화벽-설정)
- [결과 해석](#7-결과-해석)
- [Python API](#10-python-api-참고)
- [문제 해결](#11-문제-해결)
- [테스트](#12-테스트)

## 1. 지원 범위와 실행 조건

| 항목 | 조건 |
| --- | --- |
| Python | 패키지 조건은 3.11 이상, 기준 검증 버전은 3.11.9 |
| 네트워크 | 동일 IPv4 브로드캐스트 도메인 |
| bootstrap port | 기본 UDP `37020` |
| RTSP | RTSP/2.0, 인증 없는 `OPTIONS` 요청에 대한 2xx 응답 |
| 런타임 의존성 | 외부 패키지 없음, Python 표준 라이브러리만 사용 |

실제 두 장비에서 실행하려면 다음 조건도 만족해야 합니다.

- Receiver가 UDP `37020`을 수신할 수 있어야 합니다.
- Sender가 ACK를 받을 UDP source port가 방화벽에서 허용되어야 합니다.
- Receiver에서 광고된 RTSP TCP port로 접속할 수 있어야 합니다.
- Wi-Fi AP의 client isolation 또는 guest isolation이 꺼져 있어야 합니다.
- Sender와 Receiver의 `start_port` 값이 같아야 합니다.
- RTSP 서버 주소로 hostname이 아닌 숫자 IPv4를 사용해야 합니다.

## 2. 설치

프로젝트 루트, 즉 `pyproject.toml`이 있는 디렉터리에서 실행합니다.

### 2.1 Windows PowerShell

가상환경을 활성화하지 않고 그 안의 Python을 직접 사용하므로 PowerShell
execution policy의 영향을 받지 않습니다.

```powershell
Set-Location 'C:\path\to\YNBro'

python --version
python -m venv .venv

$Py = if (Test-Path .\.venv\Scripts\python.exe) {
    (Resolve-Path .\.venv\Scripts\python.exe).Path
} else {
    (Resolve-Path .\.venv\bin\python.exe).Path
}
& $Py -m pip install -e .
& $Py -c "import ynb; from ynb import sender, receiver; print(ynb.__version__)"
```

첫 설치에서는 build dependency인 `setuptools>=69`를 Python package index에서
내려받을 수 있으므로 인터넷 또는 조직의 package mirror 접근이 필요할 수
있습니다. 폐쇄망에서는 관리자가 준비한 setuptools를 먼저 설치한 뒤
`pip install --no-build-isolation -e .`을 사용하십시오.

마지막 명령의 예상 출력은 다음과 같습니다.

```text
0.0.1
```

새 PowerShell 창을 열 때마다 실제 프로젝트 경로로 이동해 다음 블록을
다시 실행하면
이 README의 `$Py` 명령을 그대로 사용할 수 있습니다.

```powershell
Set-Location 'C:\path\to\YNBro'
$Py = if (Test-Path .\.venv\Scripts\python.exe) {
    (Resolve-Path .\.venv\Scripts\python.exe).Path
} else {
    (Resolve-Path .\.venv\bin\python.exe).Path
}
```

### 2.2 Linux 또는 macOS 계열 셸

```sh
cd /path/to/YNBro

python3.11 --version
python3.11 -m venv .venv

PY=.venv/bin/python
"$PY" -m pip install -e .
"$PY" -c 'import ynb; from ynb import sender, receiver; print(ynb.__version__)'
```

Git Bash에서 Windows Python을 사용할 때는 위 블록 대신 다음처럼 설정합니다.

```sh
cd /c/path/to/YNBro

python --version
python -m venv .venv

if [ -x .venv/Scripts/python.exe ]; then
    PY=.venv/Scripts/python.exe
else
    PY=.venv/bin/python.exe
fi
"$PY" -m pip install -e .
"$PY" -c 'import ynb; from ynb import sender, receiver; print(ynb.__version__)'
```

### 2.3 설치 확인 테스트

```powershell
& $Py -m unittest discover -s tests -v
```

일반 셸에서는 다음과 같습니다.

```sh
"$PY" -m unittest discover -s tests -v
```

현재 전체 테스트는 22개이며 마지막에 `OK`가 출력되어야 합니다. 테스트는
외부 LAN에 브로드캐스트를 보내지 않고 loopback과 mock socket을 사용합니다.

## 3. 가장 빠른 로컬 확인

실제 RTSP 장비나 두 번째 PC 없이 전체 공개 API 흐름을 확인하려면 다음
End-to-End 테스트만 실행합니다.

```powershell
& $Py -m unittest tests.test_e2e -v
```

```sh
"$PY" -m unittest tests.test_e2e -v
```

이 테스트는 실제 loopback UDP/TCP socket과 테스트용 RTSP 서버를 사용해
다음을 검사합니다.

```text
ADVERTISE → ACK → DETAIL → ACK → RTSP/2.0 OPTIONS → 결과 dict
```

다만 `127.0.0.1`을 사용하는 기능 시험이므로 실제 LAN 브로드캐스트 도달성은
검증하지 않습니다.

## 4. 한 컴퓨터에서 수동 loopback 실행

이 절차는 세 개의 터미널을 사용합니다.

1. 터미널 A에서 테스트용 RTSP/2.0 서버를 실행합니다.
2. 터미널 B에서 Receiver를 실행합니다.
3. Receiver가 기다리는 동안 터미널 C에서 Sender를 실행합니다.

모든 터미널에서 먼저 프로젝트 루트로 이동하고 `$Py` 또는 `$PY`를
설정하십시오.

### 4.1 터미널 A: 테스트용 RTSP/2.0 서버

다음 서버는 요청을 출력하고 `RTSP/2.0 200 OK`로 응답합니다. 여러 연결을
연속해서 받을 수 있으며 `Ctrl+C`로 종료합니다. 개발 확인 전용이며 인증
기능이 없습니다.

PowerShell:

```powershell
$FakeRtspCode = @'
import socket

host = "127.0.0.1"
port = 8554
response = (
    b"RTSP/2.0 200 OK\r\n"
    b"CSeq: 1\r\n"
    b"Content-Length: 0\r\n"
    b"\r\n"
)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    print(f"fake RTSP server listening on {host}:{port}", flush=True)

    try:
        while True:
            connection, peer = server.accept()
            with connection:
                connection.settimeout(5)
                request = bytearray()
                try:
                    while b"\r\n\r\n" not in request and len(request) < 16384:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        request.extend(chunk)

                    first_line = bytes(request).split(b"\r\n", 1)[0]
                    print(f"request from {peer}: {first_line!r}", flush=True)
                    if b"\r\n\r\n" in request:
                        connection.sendall(response)
                except OSError as exc:
                    print(f"connection error from {peer}: {exc}", flush=True)
    except KeyboardInterrupt:
        print("fake RTSP server stopped")
'@

$FakeRtspCode | & $Py -
```

일반 셸:

```sh
"$PY" - <<'PY'
import socket

host = "127.0.0.1"
port = 8554
response = (
    b"RTSP/2.0 200 OK\r\n"
    b"CSeq: 1\r\n"
    b"Content-Length: 0\r\n"
    b"\r\n"
)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen()
    print(f"fake RTSP server listening on {host}:{port}", flush=True)

    try:
        while True:
            connection, peer = server.accept()
            with connection:
                connection.settimeout(5)
                request = bytearray()
                try:
                    while b"\r\n\r\n" not in request and len(request) < 16384:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        request.extend(chunk)

                    first_line = bytes(request).split(b"\r\n", 1)[0]
                    print(f"request from {peer}: {first_line!r}", flush=True)
                    if b"\r\n\r\n" in request:
                        connection.sendall(response)
                except OSError as exc:
                    print(f"connection error from {peer}: {exc}", flush=True)
    except KeyboardInterrupt:
        print("fake RTSP server stopped")
PY
```

### 4.2 터미널 B: Receiver

PowerShell:

```powershell
& $Py -c "from pprint import pprint; from ynb import receiver; pprint(receiver.discover(timeout=30, start_port=37020, bind_host='127.0.0.1'))"
```

일반 셸:

```sh
"$PY" -c 'from pprint import pprint; from ynb import receiver; pprint(receiver.discover(timeout=30, start_port=37020, bind_host="127.0.0.1"))'
```

Receiver는 최대 30초 동안 기다립니다. 이 시간이 지나기 전에 Sender를
실행해야 합니다.

### 4.3 터미널 C: Sender

PowerShell:

```powershell
& $Py -c "from ynb import sender; print(sender.advertise(device_id='02:00:00:00:00:01', ip='127.0.0.1', rtsp_port=8554, rtsp_path='/stream', timeout=10, start_port=37020, broadcast_address='127.0.0.1', bind_host='127.0.0.1'))"
```

일반 셸:

```sh
"$PY" -c 'from ynb import sender; print(sender.advertise(device_id="02:00:00:00:00:01", ip="127.0.0.1", rtsp_port=8554, rtsp_path="/stream", timeout=10, start_port=37020, broadcast_address="127.0.0.1", bind_host="127.0.0.1"))'
```

예상 Sender 출력:

```text
True
```

예상 Receiver 결과의 핵심 값:

```python
{
    "device_id": "02:00:00:00:00:01",
    "ip": "127.0.0.1",
    "rtsp_port": 8554,
    "rtsp_path": "/stream",
    "rtsp_uri": "rtsp://127.0.0.1:8554/stream",
    "rtsp_connected": True,
}
```

이 예제의 `broadcast_address="127.0.0.1"`은 테스트를 위한 유니캐스트
주입입니다. 실제 브로드캐스트 시험으로 해석해서는 안 됩니다.

## 5. 두 컴퓨터에서 실제 LAN 실행

전체 실행 순서는 다음과 같습니다.

1. RTSP Server를 실행하거나 기존 서버의 동작을 확인합니다.
2. Receiver를 실행해 ADVERTISE를 기다립니다.
3. Receiver가 기다리는 동안 Sender를 실행합니다.

### 5.1 예제 배치

아래 주소는 설명을 위한 예입니다. 실제 NIC의 주소와 subnet prefix를 먼저
확인하고 값을 바꾸십시오.

| 항목 | 예제 값 |
| --- | --- |
| Sender 및 RTSP Server PC | `192.168.1.10/24` |
| Receiver PC | `192.168.1.20/24` |
| directed broadcast | `192.168.1.255` |
| bootstrap UDP port | `37020` |
| Sender ACK 수신 UDP port | `37021` |
| RTSP TCP port | `8554` |
| RTSP path | `/stream` |

RTSP Server는 Sender와 다른 세 번째 장비에 있어도 됩니다. 이 경우
Sender의 `ip`에는 세 번째 장비의 실제 IPv4를 넣습니다.

### 5.2 IP와 MAC 주소 확인

Windows PowerShell:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.AddressState -eq 'Preferred'
    } |
    Format-Table InterfaceAlias, IPAddress, PrefixLength

Get-NetAdapter |
    Where-Object Status -eq 'Up' |
    Format-Table Name, MacAddress
```

Windows의 MAC 주소는 보통 하이픈으로 표시됩니다. YNB 형식은 콜론이므로
다음처럼 변환할 수 있습니다.

```powershell
$deviceId = (Get-NetAdapter -Name 'Ethernet').MacAddress -replace '-', ':'
$deviceId
```

`Ethernet`은 예시 이름입니다. 앞 명령에서 확인한 실제 adapter 이름으로
바꾸십시오. 출력한 값을 아래 Sender 예제의 `AA:BB:CC:DD:EE:FF` 자리에
직접 넣어야 하며, `$deviceId` 변수가 Python 코드에 자동으로 삽입되지는
않습니다.

Linux:

```sh
ip -4 addr
ip link
```

directed broadcast 주소는 임의로 마지막 octet을 255로 정하지 말고 실제
prefix로 계산합니다.

```powershell
& $Py -c "import ipaddress; print(ipaddress.ip_interface('192.168.1.10/24').network.broadcast_address)"
```

```sh
"$PY" -c 'import ipaddress; print(ipaddress.ip_interface("192.168.1.10/24").network.broadcast_address)'
```

### 5.3 RTSP Server 준비

실제 RTSP/2.0 서버가 있다면 해당 서버가 Receiver에서 접근 가능한지 먼저
확인합니다. 테스트용 서버를 사용할 때는 4.1의 코드에서 다음 한 줄을
바꾸어 Sender 또는 별도 RTSP PC에서 실행합니다.

```python
host = "0.0.0.0"
```

`0.0.0.0`은 listen 용도일 뿐 광고할 주소가 아닙니다. Sender의 `ip`에는
예제의 `192.168.1.10`처럼 Receiver가 접근할 실제 LAN IPv4를 넣습니다.

### 5.4 Receiver PC에서 먼저 실행

PowerShell:

```powershell
$ReceiverCode = @'
from pprint import pprint
from ynb import receiver

result = receiver.discover(
    timeout=60,
    start_port=37020,
    bind_host="0.0.0.0",
)
pprint(result)
'@

$ReceiverCode | & $Py -
```

일반 셸:

```sh
"$PY" - <<'PY'
from pprint import pprint
from ynb import receiver

result = receiver.discover(
    timeout=60,
    start_port=37020,
    bind_host="0.0.0.0",
)
pprint(result)
PY
```

### 5.5 Sender PC에서 실행

아래 예제는 ACK 수신 port를 `37021`로 고정해 방화벽 규칙을 예측 가능하게
합니다. port가 이미 사용 중이면 다른 사용 가능한 UDP port로 양쪽 방화벽과
`bind_port`를 함께 바꾸십시오.

`AA:BB:CC:DD:EE:FF`와 `192.168.1.10`은 placeholder입니다. 앞 단계에서
확인한 Sender 장비 식별자와 RTSP Server 주소로 반드시 교체하십시오.

PowerShell:

```powershell
$SenderCode = @'
from ynb import sender

acknowledged = sender.advertise(
    device_id="AA:BB:CC:DD:EE:FF",
    ip="192.168.1.10",
    rtsp_port=8554,
    rtsp_path="/stream",
    timeout=15,
    start_port=37020,
    broadcast_address="255.255.255.255",
    bind_host="192.168.1.10",
    bind_port=37021,
)
print("DETAIL ACK received:", acknowledged)
'@

$SenderCode | & $Py -
```

일반 셸:

```sh
"$PY" - <<'PY'
from ynb import sender

acknowledged = sender.advertise(
    device_id="AA:BB:CC:DD:EE:FF",
    ip="192.168.1.10",
    rtsp_port=8554,
    rtsp_path="/stream",
    timeout=15,
    start_port=37020,
    broadcast_address="255.255.255.255",
    bind_host="192.168.1.10",
    bind_port=37021,
)
print("DETAIL ACK received:", acknowledged)
PY
```

limited broadcast가 VPN 또는 다중 NIC 때문에 올바른 인터페이스로 나가지
않으면, 계산한 directed broadcast를 사용합니다.

```python
broadcast_address="192.168.1.255"
```

YNB는 이 값의 IPv4 문법만 검사하며 실제 broadcast 주소인지 판별하지
않습니다.

### 5.6 재실행

0.0.1에는 UDP 자동 재전송이 없습니다. 패킷이 유실되거나 timeout이 발생하면
Receiver를 다시 실행한 뒤 Sender를 다시 실행하십시오. Receiver 한 번의
호출은 첫 번째 유효 Sender 한 대만 처리하고 종료합니다.

## 6. 방화벽 설정

다음 명령은 운영체제 방화벽을 변경합니다. 관리자 권한으로 실행하기 전에
port와 network profile이 실제 환경에 맞는지 확인하십시오. 신뢰하는 Private
LAN에만 허용하는 것이 좋습니다.

### 6.1 Windows

현재 network profile을 확인합니다.

```powershell
Get-NetConnectionProfile
```

Receiver PC의 UDP start port:

```powershell
New-NetFirewallRule `
    -DisplayName 'YNB Receiver UDP 37020' `
    -Direction Inbound `
    -Action Allow `
    -Protocol UDP `
    -LocalPort 37020 `
    -RemoteAddress LocalSubnet `
    -Profile Private
```

Sender가 예제처럼 `bind_port=37021`을 사용할 때:

```powershell
New-NetFirewallRule `
    -DisplayName 'YNB Sender ACK UDP 37021' `
    -Direction Inbound `
    -Action Allow `
    -Protocol UDP `
    -LocalPort 37021 `
    -RemoteAddress LocalSubnet `
    -Profile Private
```

테스트 RTSP Server PC:

```powershell
New-NetFirewallRule `
    -DisplayName 'YNB Test RTSP TCP 8554' `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8554 `
    -RemoteAddress LocalSubnet `
    -Profile Private
```

시험이 끝난 뒤 더 이상 필요하지 않은 규칙은 이름을 정확히 확인하고
제거할 수 있습니다.

```powershell
Remove-NetFirewallRule -DisplayName 'YNB Receiver UDP 37020'
Remove-NetFirewallRule -DisplayName 'YNB Sender ACK UDP 37021'
Remove-NetFirewallRule -DisplayName 'YNB Test RTSP TCP 8554'
```

### 6.2 Linux UFW 예

아래 subnet은 예제입니다. 실제 LAN subnet으로 바꾸고, 각 명령은 표시된
역할의 PC에서만 실행하십시오.

```sh
# Receiver PC
sudo ufw allow from 192.168.1.0/24 to any port 37020 proto udp

# bind_port=37021을 사용하는 Sender PC
sudo ufw allow from 192.168.1.0/24 to any port 37021 proto udp

# 테스트 RTSP Server PC
sudo ufw allow from 192.168.1.0/24 to any port 8554 proto tcp

sudo ufw status
```

시험이 끝나 규칙이 필요하지 않으면 규칙을 만든 해당 PC에서 삭제합니다.

```sh
# 각 PC에서 자신에게 해당하는 규칙만 실행
sudo ufw delete allow from 192.168.1.0/24 to any port 37020 proto udp
sudo ufw delete allow from 192.168.1.0/24 to any port 37021 proto udp
sudo ufw delete allow from 192.168.1.0/24 to any port 8554 proto tcp
```

### 6.3 macOS

LAN 주소는 `ifconfig`로 확인할 수 있습니다. 방화벽을 사용하는 경우
System Settings의 Network → Firewall → Options에서 실행에 사용하는 Python을
허용하십시오. 조직에서 별도 packet filter를 사용한다면 관리자 정책에
따라 UDP `37020`, Sender의 고정 ACK port와 RTSP TCP port를 제한적으로
허용해야 합니다.

## 7. 결과 해석

### 7.1 Sender 반환값과 예외

| 값 | 의미 |
| --- | --- |
| `True` | Receiver로부터 DETAIL ACK를 받음 |
| `False` | ACK timeout 또는 UDP socket 오류 |

Sender의 `True`는 RTSP 성공을 뜻하지 않습니다. RTSP 결과는 Receiver가
반환한 `rtsp_connected`에서 확인합니다.

MAC, endpoint IPv4, port, path, timeout 또는 bind host의 타입이 잘못되면
`ValueError`가 발생합니다.
직렬화할 수 없거나 UDP 데이터그램 상한을 넘는 메시지는 `ValueError`의
하위 타입인 `MessageError`가 발생할 수 있습니다. 두 예외는 반환값이
아니므로 필요하면 `try`/`except`로 처리하십시오.

### 7.2 Receiver 반환값

| 값 | 의미 |
| --- | --- |
| `None` | UDP 발견/DETAIL 교환 미완료, timeout 또는 socket 오류 |
| dict + `rtsp_connected=True` | UDP 교환과 RTSP/2.0 OPTIONS 2xx 응답 확인 |
| dict + `rtsp_connected=False` | UDP 교환은 완료했지만 RTSP probe 실패 |

잘못된 timeout, start port 또는 문자열이 아닌 bind host는 `ValueError`를
발생시킵니다. 문자열 bind host를 운영체제가 해석하거나 bind하지 못한 경우는
예외 대신 `None`입니다.

Receiver의 전체 결과 형식:

```python
{
    "device_id": "AA:BB:CC:DD:EE:FF",
    "ip": "192.168.1.10",
    "rtsp_port": 8554,
    "rtsp_path": "/stream",
    "rtsp_uri": "rtsp://192.168.1.10:8554/stream",
    "rtsp_connected": True,
}
```

`rtsp_connected=True`도 영상 재생 성공을 보장하지 않습니다. 현재 probe는
`DESCRIBE`, `SETUP`, `PLAY`를 수행하지 않습니다.

## 8. 실제 RTSP 서버 호환 조건

Sender의 endpoint 인자는 다음 의미를 가집니다.

| 인자 | 의미 |
| --- | --- |
| `ip` | Receiver가 접근할 RTSP 서버의 숫자 IPv4 |
| `rtsp_port` | RTSP 서버 TCP port, 정수 `1..65535` |
| `rtsp_path` | `/`로 시작하는 RTSP 자원 경로 |

`ip`에 hostname 또는 `rtsp://...` 전체 URI를 넣으면 안 됩니다. RTSP 서버가
Sender와 다른 장비여도 괜찮지만 Receiver에서 해당 endpoint에 접근할 수
있어야 합니다.

현재 probe는 다음 요청을 보냅니다.

```text
OPTIONS rtsp://192.168.1.10:8554/stream RTSP/2.0
CSeq: 1
User-Agent: ynb/0.0.1

```

다음 응답은 모두 `rtsp_connected=False`입니다.

- `RTSP/1.0 200 OK`
- `RTSP/2.0 401 Unauthorized`
- RTSP/2.0 3xx, 4xx, 5xx
- TCP 연결 거부 또는 응답 timeout
- header가 끝나지 않거나 status line이 잘못된 응답

많은 기존 IP 카메라는 RTSP/1.0 또는 인증을 요구합니다. TCP port가 열려
있어도 이 조건 때문에 YNB 0.0.1의 결과가 `False`일 수 있습니다.

UDP 발견과 분리해 RTSP probe만 검사하려면 다음 명령을 사용합니다.

```powershell
& $Py -c "from ynb.connecter import probe_rtsp; print(probe_rtsp('192.168.1.10', 8554, '/stream', timeout=5))"
```

```sh
"$PY" -c 'from ynb.connecter import probe_rtsp; print(probe_rtsp("192.168.1.10", 8554, "/stream", timeout=5))'
```

## 9. 동작 원리

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

### 9.1 브로드캐스트와 유니캐스트

ADVERTISE만 같은 네트워크의 여러 장비가 받을 수 있도록 브로드캐스트합니다.
Receiver가 ACK를 보내면 Sender는 `recvfrom()`이 알려 준 실제 peer
`(IPv4, UDP port)`로 DETAIL을 유니캐스트합니다.

peer는 UDP 교환 상대이고 DETAIL의 `ip`는 RTSP 접속 목적지입니다. 두 주소는
같을 필요가 없습니다.

### 9.2 하나의 timeout 예산

Sender는 두 ACK 교환 전체에, Receiver는 UDP 교환과 RTSP probe 전체에
하나의 timeout을 사용합니다. 잘못된 패킷이 들어올 때마다 timeout이 새로
시작되지 않습니다.

### 9.3 Wire 메시지

ADVERTISE:

```json
{
  "message_type": "ADVERTISE",
  "device_id": "AA:BB:CC:DD:EE:FF"
}
```

ADVERTISE ACK:

```json
{
  "message_type": "ACK",
  "device_id": "AA:BB:CC:DD:EE:FF",
  "ack_for": "ADVERTISE"
}
```

DETAIL:

```json
{
  "message_type": "DETAIL",
  "device_id": "AA:BB:CC:DD:EE:FF",
  "ip": "192.168.1.10",
  "rtsp_port": 8554,
  "rtsp_path": "/stream"
}
```

DETAIL ACK:

```json
{
  "message_type": "ACK",
  "device_id": "AA:BB:CC:DD:EE:FF",
  "ack_for": "DETAIL"
}
```

모든 메시지는 UDP 데이터그램 하나에 담긴 UTF-8 JSON 객체입니다. 누락
필드뿐 아니라 정의되지 않은 추가 필드도 거부합니다.

## 10. Python API 참고

### 10.1 `sender.advertise()`

```python
from ynb import sender

acknowledged = sender.advertise(
    device_id="AA:BB:CC:DD:EE:FF",
    ip="192.168.1.10",
    rtsp_port=8554,
    rtsp_path="/stream",
    timeout=10,
)
```

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `device_id` | 필수 | 콜론 형식 MAC 문자열 |
| `ip` | 필수 | Receiver가 접속할 RTSP 서버 IPv4 |
| `rtsp_port` | 필수 | RTSP TCP port |
| `rtsp_path` | 필수 | `/`로 시작하는 경로 |
| `timeout` | `5` | 두 UDP 왕복 전체의 최대 시간 |
| `start_port` | `37020` | ADVERTISE 목적지 UDP port |
| `broadcast_address` | `255.255.255.255` | limited 또는 directed broadcast 주소 |
| `bind_host` | `0.0.0.0` | Sender UDP socket을 bind할 로컬 주소 |
| `bind_port` | `0` | Sender source port, 0이면 OS가 임시 port 선택 |

모든 endpoint 값은 socket을 열기 전에 검증됩니다.

### 10.2 `receiver.discover()`

```python
from ynb import receiver

device = receiver.discover(
    timeout=60,
    start_port=37020,
    bind_host="0.0.0.0",
)
```

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `timeout` | `5` | UDP 교환과 RTSP probe 전체의 최대 시간 |
| `start_port` | `37020` | ADVERTISE를 받을 UDP port |
| `bind_host` | `0.0.0.0` | 모든 로컬 IPv4 인터페이스에서 수신 |

Receiver는 호출 한 번에 장비 한 대만 반환합니다.

## 11. 문제 해결

### `ModuleNotFoundError: No module named 'ynb'`

패키지를 설치한 Python과 실행 중인 Python이 다를 가능성이 큽니다. 모든
명령에서 Windows의 `$Py` 또는 일반 셸의 `$PY`를 사용하고 다음을 확인합니다.

```powershell
& $Py -c "import sys, ynb; print(sys.executable); print(ynb.__file__)"
```

설치 중 `Could not find a version that satisfies the requirement setuptools>=69`
오류가 나면 package index, proxy 또는 사내 mirror 접근을 확인합니다. 폐쇄망
환경은 위 설치 절의 `--no-build-isolation` 안내를 따르십시오.

### Sender가 `False`, Receiver가 `None`

- Receiver를 Sender보다 먼저 실행했는지 확인합니다.
- 양쪽 `start_port`가 같은지 확인합니다.
- Receiver UDP port와 Sender ACK port의 방화벽을 확인합니다.
- `bind_host`가 해당 PC에 실제 존재하는 IPv4인지 확인합니다.
- UDP port가 다른 process에서 사용 중인지 확인합니다.
- 패킷 유실 가능성이 있으므로 Receiver부터 다시 실행합니다.

### Sender는 `True`, Receiver는 `rtsp_connected=False`

UDP 발견은 정상입니다. 다음 RTSP 조건을 확인합니다.

- endpoint IP, TCP port와 path
- RTSP Server의 listen 주소와 방화벽
- RTSP/2.0 지원 여부
- 인증 없이 OPTIONS에 2xx를 반환하는지 여부

### 같은 Wi-Fi인데 발견되지 않음

같은 SSID라도 guest network, VLAN 또는 AP client isolation 때문에
브로드캐스트가 차단될 수 있습니다. 두 PC의 subnet prefix와 AP 설정을
확인합니다.

### VPN 또는 여러 NIC가 있음

Sender의 `bind_host`를 실제 LAN IPv4로 고정하고 그 subnet의 directed
broadcast를 사용합니다.

### `ValueError`가 발생함

다음 형식을 확인합니다.

- MAC: `AA:BB:CC:DD:EE:FF`
- IP: hostname이 아닌 숫자 IPv4
- port: 정수 `1..65535`
- path: `/`로 시작하고 줄바꿈 문자가 없음
- timeout: 0 이상의 유한한 수

### Windows 상태 확인 명령

```powershell
Get-NetUDPEndpoint -LocalPort 37020
Get-NetUDPEndpoint -LocalPort 37021
Get-NetTCPConnection -State Listen -LocalPort 8554
Test-NetConnection -ComputerName 192.168.1.10 -Port 8554
```

### Linux 상태 확인 명령

```sh
ss -lunp | grep 37020
ss -lunp | grep 37021
ss -ltnp | grep 8554
```

### macOS 상태 확인 명령

```sh
ifconfig
lsof -nP -iUDP:37020
lsof -nP -iUDP:37021
lsof -nP -iTCP:8554 -sTCP:LISTEN
```

## 12. 테스트

전체 테스트:

```powershell
& $Py -m unittest discover -s tests -v
```

영역별 테스트:

```powershell
& $Py -m unittest tests.test_protocol -v
& $Py -m unittest tests.test_sender -v
& $Py -m unittest tests.test_receiver -v
& $Py -m unittest tests.test_connecter -v
& $Py -m unittest tests.test_e2e -v
```

| 파일 | 검사 대상 |
| --- | --- |
| `tests/test_protocol.py` | wire schema, UTF-8 JSON, 입력 경계 |
| `tests/test_sender.py` | broadcast 옵션, 실제 ACK peer, 잘못된 ACK |
| `tests/test_receiver.py` | malformed 입력, peer와 device ID 고정 |
| `tests/test_connecter.py` | URI, OPTIONS/CSeq, 성공·거부·timeout |
| `tests/test_e2e.py` | 공개 API 전체 성공 및 RTSP 실패 결과 |

## 13. 보안 전제와 알려진 제한

0.0.1은 인증, 메시지 서명, 암호화를 제공하지 않습니다. 신뢰할 수 있는
동일 LAN에서만 사용해야 합니다.

Receiver는 DETAIL에 담긴 endpoint로 TCP 연결을 시도합니다. 신뢰하지 못하는
네트워크에서 실행하면 공격자가 Receiver의 임의 IPv4와 port 접속을 유도할
수 있습니다. 실제 배포에서는 방화벽과 허용 네트워크 범위를 제한하십시오.

현재 제공하지 않는 기능:

- UDP 자동 재전송
- `message_id`와 replay 방지
- 중복 및 재정렬 처리
- callback과 장비 registry
- 비동기 또는 상시 실행 Receiver
- RTSP 인증과 영상 재생
- IPv6 또는 다른 subnet을 통한 자동 발견
- 암호화와 발신자 인증

## 14. 패키지 구조와 문서

```text
YNBro/
├── pyproject.toml
├── README.md
├── SRS.md
├── SDS.md
├── SRS_IMPLEMENTATION_REPORT.md
├── src/
│   └── ynb/
│       ├── __init__.py
│       ├── _protocol.py
│       ├── sender.py
│       ├── receiver.py
│       └── connecter.py
└── tests/
```

- [`SRS.md`](SRS.md): 검증 가능한 소프트웨어 요구사항
- [`SDS.md`](SDS.md): 모듈 구조, 상태 머신, 오류 및 보안 설계
- [`SRS_IMPLEMENTATION_REPORT.md`](SRS_IMPLEMENTATION_REPORT.md): 요구사항별 구현 현황과 검증 결과
