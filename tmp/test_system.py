from rtsp_bootstrap import BootstrapReceiver


with BootstrapReceiver(rtsp_timeout=2.0) as receiver:
    devices = receiver.discover(timeout=10.0)

for device in devices:
    print(device["device_id"])
    print(device["rtsp_uri"])
