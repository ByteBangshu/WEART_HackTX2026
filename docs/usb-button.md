# Capture button quick start

Use the USB-transfer firmware described in hardware.md and close any serial monitor or standalone USB bridge that holds the device port.

Install project dependencies (`python -m pip install -e .`), including pyserial. Before starting the live app in PowerShell, set the actual ESP32 port:

```powershell
$env:WEART_USB_PORT = "COM5"
$env:WEART_ALLOW_UNBOUNDED_SEARCH = "true"
python tools/run.py --live
```

The live app also needs MODEL_API_KEY configured. Replace COM5 with your device's port (on Linux, for example, /dev/ttyUSB0). The bridge requires a local HTTP origin.

Click **Capture from ESP32**, wait about a second for the bridge to open the port, then short-press the physical capture button. The host terminal prints when it is listening. The bridge waits up to two minutes for a photo, submits it to the existing processing pipeline, and the UI automatically shows the resulting briefing. Duplicate capture launches are rejected. Transfer errors and timeouts allow a retry; details appear in the host terminal.

The image is sent to Meta in live mode, and research uses the existing search configuration. This minimal button does not remotely trigger the camera or change firmware.
