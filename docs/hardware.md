# ESP32-S3 hardware and commissioning

## Identify the board

The current board listing identifies an **ESP32-S3-N16R8** module with an OV3660 camera. Its N16R8 configuration uses 16 MB flash and 8 MB octal PSRAM; firmware defaults select these memory settings. The linked [camera example](https://github.com/MahdMalik/MiniModelBot/blob/main/main/src/camera.cpp) identifies the following onboard camera connections for this ESP32-S3-CAM layout:

| Camera signal | ESP32 GPIO |
|---|---:|
| D0–D7 | 11, 9, 8, 10, 12, 18, 17, 16 |
| XCLK | 15 |
| PCLK | 13 |
| VSYNC | 6 |
| HREF | 7 |
| SCCB SDA / SCL | 4 / 5 |
| PWDN / RESET | Not connected (-1) |

These are PCB connections, not jumper wires. The firmware defaults use this mapping and GPIO 0 (the board's BOOT button) for capture; indicator LEDs are disabled. No breadboard is required. If the board is mounted on one, it only needs its header pins seated for support/power access; do not wire the camera signals to the breadboard. The source example is for an ESP32-S3-CAM layout, so stop and compare the board silkscreen/revision if yours differs.

## BOM / wiring

| Part | Requirement |
|---|---|
| ESP32-S3 camera board | PSRAM required; 8 MB recommended for JPEG/TLS headroom |
| OV2640/OV5640 | Board-compatible module/ribbon; autofocus not implemented |
| USB power | Stable 5 V, at least 1 A, into designated board input; never 5 V to GPIO |
| Button | Active-low GPIO to ground with pull-up; RTC pin for optional deep sleep |
| RGB LED | Three discrete active-high GPIO channels with resistors; addressable LEDs need a different driver |
| Standoff/hood | Matte finish, initial 12–20 cm distance adjusted to actual focus |
| Optional battery | Protected battery/charger circuitry; no voltage-sense GPIO assumed |

Camera signals: D0–D7, XCLK, PCLK, VSYNC, HREF, SCCB SDA/SCL, optional RESET/PWDN. Follow the manufacturer mapping and ribbon orientation. Never reuse camera/flash/PSRAM/USB pins for controls.

## Build and flash

Use official [ESP-IDF 5.5](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/get-started/index.html):

Open the repository's `firmware` folder in VS Code, or activate ESP-IDF 5.5 in a terminal before running:

```text
cd firmware
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p YOUR_SERIAL_PORT flash monitor
```

In VS Code, run `ESP-IDF: Import ESP-IDF Project` and choose this `firmware` folder, then run `ESP-IDF: Build your Project`. The build resolves the pinned camera component and generates `firmware/build/compile_commands.json`, which the checked-in IntelliSense configuration uses to resolve ESP-IDF headers. If C imports remain unresolved before the first successful configure, build the project once or run `ESP-IDF: Run idf.py reconfigure task`.

Camera driver 2.1.8 is pinned in `main/idf_component.yml`; Component Manager downloads it and its dependencies into the ignored `managed_components` directory. Keep `dependencies.lock` committed so builds use the resolved component versions. The default partition layout reserves a 3 MB factory application (no OTA slots). CI builds the unset-pin safe-mode variant; this does not validate hardware. Local firmware compilation status is recorded in verification.md.

## USB capture to the local app

For direct USB transfer, install the project dependencies, activate ESP-IDF, and use menuconfig to enable **WEART board configuration → Send captured JPEG over USB serial instead of Wi-Fi**. This opt-in firmware bypasses Wi-Fi and writes each button-triggered JPEG as raw bytes to the USB serial console. Build and flash the application:

```text
cd firmware
idf.py menuconfig
idf.py build
idf.py -p YOUR_SERIAL_PORT app-flash
```

Start the local app in live mode in a second terminal. This sends the full captured image to Meta for processing; a person summary also uses web search, whose provider-side cost has no verified hard ceiling. Enter the key at the hidden prompt instead of putting it in shell history:

```text
read -rsp 'Meta Model API key: ' MODEL_API_KEY; printf '\n'
export MODEL_API_KEY WEART_PROVIDER=meta WEART_ALLOW_UNBOUNDED_SEARCH=true
.venv/bin/python tools/run.py --live
```

Keep `MODEL_API_KEY` in a private local environment; never put it in chat or firmware. After stopping the app, run `unset MODEL_API_KEY`. The bridge refuses mock mode and will not capture or submit an image unless live mode and search opt-in are enabled. In another terminal, install project dependencies if needed and start the USB-to-app bridge:

```text
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python tools/esp32_usb_capture.py --port YOUR_SERIAL_PORT
```

When the bridge says it is listening, short-press the ESP32 capture button. It transfers the JPEG over USB, submits it to the local app, and prints the resulting sourced summary. The image comes directly from the ESP32, not a manual browser upload. To restore Wi-Fi capture, disable the USB-transfer option in menuconfig, then run `idf.py build` and `idf.py -p YOUR_SERIAL_PORT app-flash`; this app-only flash preserves NVS. USB mode is disabled by default.

## Pair

1. First boot, or hold the configured button for three seconds during boot.
2. Join `WEART-Setup` using its one-boot WPA2 password shown on physical USB serial. Visit `http://192.168.4.1`; automatic captive-portal detection is not implemented.
3. Enter 2.4 GHz WPA2 Wi-Fi credentials, exact HTTPS host origin, unique device ID, and the host CA PEM. Never enter the host private key or model API key.
4. In the authenticated host UI, create a pairing code and enter it within five minutes.
5. Save/reboot. Device syncs time, validates host TLS, pairs and saves its token to NVS. Host persists only the token hash.
6. Replacing a paired ID requires revocation through authenticated `DELETE /v1/devices/{id}`, or a new ID. Physical reprovisioning is required after token revocation.

Keep NVS encryption and secure boot as explicit board commissioning steps; neither is blindly enabled on an unknown board.

## Controls / states

Short press: discard four warm-up frames, capture three UXGA JPEGs, keep largest, upload with stable capture ID, clear/free copied buffer, shut down camera, poll status. Long press (~1.5 seconds, on release) cancels or returns LED to ready. A blocking HTTP call may delay cancellation until it returns. Two retries reuse the capture ID. HTTP operation timeout is 15 seconds; a separate 5-second connect timeout is not implemented.

| State | LED |
|---|---|
| Boot/connecting | Blue blink |
| Provisioning | Magenta blink |
| Ready/done | Green |
| Capturing | White |
| Uploading | Blue + green blink |
| Processing | Amber blink |
| Retake/rejected | Two red flashes |
| Error | Slow red blink |

JPEG length is a cheap heuristic: noise/texture can increase size without better focus. Host quality checks are a second signal. Fixed-focus cameras need physical distance tuning.

Camera deinitializes after capture/idle; Wi-Fi uses modem sleep. Optional five-minute deep sleep requires a verified RTC button pin and is off by default. Full light sleep, BSSID caching, battery measurements, double-press aim preview, autofocus, display, audio and signed OTA are deferred. Watchdog and brownout detection are enabled; repeated panic/watchdog/brownout resets enter safe provisioning. Validate timings on actual hardware.

## Acceptance not yet run

50 physical captures; Wi-Fi drop during upload; lost-response retry; cancellation; low light/glare; failed time sync; wrong certificate; weak supply/brownout; sleep/wake. Record capture→extraction and capture→brief p50/p95. Do not claim 95% reliability, 25-second median or battery endurance without measurements.
