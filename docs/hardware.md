# ESP32-S3 hardware and commissioning

## Identify the board

Get manufacturer, revision, camera sensor, PSRAM/flash capacities and schematic. **No numeric pin map is guessed.** In `menuconfig → WEART board configuration`, all pins default to -1; camera initialization requires confirmed, valid, nonduplicated pins. Checks cannot detect every board-specific reservation: review USB, flash, PSRAM and boot strapping pins manually. Select correct quad/octal PSRAM mode.

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

```text
cd firmware
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p YOUR_SERIAL_PORT flash monitor
```

Camera driver 2.1.8 is pinned. The default partition layout requires at least 4 MB flash and reserves a 3 MB factory application (no OTA slots). Confirm actual flash size and PSRAM mode before flashing. CI builds the unset-pin safe-mode variant; this does not validate hardware. Local firmware compilation status is recorded in verification.md.

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
