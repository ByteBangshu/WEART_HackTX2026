# Legacy networking assistant prototype (superseded by the root README)

**Recommended ESP32 setup:** ESP32 camera → Wi-Fi JPEG snapshot → Python on your computer → Muse Spark badge OCR → public company bio search → résumé-based advice → the same computer's terminal.

The ESP32 only captures and serves a photo. Python and Muse Spark do the analysis. You do **not** need an Arduino board or a Raspberry Pi. An ESP32 without a camera module cannot take an image; use an ESP32-CAM or another ESP32 camera board. The *Arduino IDE* can still be used to flash ESP32 firmware if available; it does not mean using Arduino hardware.

## 1. Set up the ESP32 camera

Flash Espressif's `CameraWebServer` example for **your exact board model**, set your Wi-Fi name/password, and read its IP address from its serial output. Example source: https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer

The official example's snapshot endpoint is `http://ESP32_IP/capture`. Open that address in your computer's browser first. You should see a single JPEG picture of the badge. Adjust the card's position, lighting, focus, and camera resolution until the printed name and company are legible. Use a still snapshot; live video is unnecessary.

Both ESP32 and computer must be able to communicate on the same local network. Event Wi-Fi may isolate devices; a personal hotspot can avoid that. The snapshot endpoint is normally plain HTTP on your local network, so use a trusted network for a demo.

## 2. Run the pipeline on your computer

Requires Python 3.9+, a Meta Model API key, and your résumé saved in plain UTF-8 text as `my_resume.txt`. No pip packages are required. In PowerShell, from the folder containing `pi_pipeline.py`:

```powershell
$env:MODEL_API_KEY="your-meta-model-api-key"
python pi_pipeline.py --resume my_resume.txt --esp32-url http://ESP32_IP/capture
```

On Linux/macOS, use `export MODEL_API_KEY='your-meta-model-api-key'` and `python3`. Replace `ESP32_IP` with the IP printed by the board. Run the command again for each card. The program downloads one photo to a temporary file, sends it and your résumé to Meta's API, prints the result, and removes the temporary photo.

While developing, you can skip hardware and use an existing clear image:

```powershell
python pi_pipeline.py --resume my_resume.txt --image badge.jpg
```

## Alternate Raspberry Pi path

The earlier Pi path still works: run `python3 pi_pipeline.py --resume my_resume.txt` directly on a Pi with `rpicam-still` or `libcamera-still`. To forward the Pi's terminal result to a second computer, run `computer_receiver.py` there and supply `--receiver` and a shared `RECEIVER_TOKEN` as in the earlier version. With ESP32, run the pipeline **on your computer**, so this receiver is unnecessary.

## What each stage does

1. Muse Spark reads `name`, `company`, and optional `job_title` from the image. Missing name/company stops the run.
2. Muse Spark searches for a public official company bio; missing bio yields no profile facts. The research prompt excludes LinkedIn.
3. Muse Spark compares available facts with the résumé to create a short summary, overlap, two talking points, and an opening question.
4. The result appears in the computer terminal, including the source URL or “No official bio found.”

The model's research response is **not independently verified by this program**. Check the cited company page before using the talking points. Poor image quality may cause OCR errors. The name/company lookup can fail for people without published bios; this is an expected fallback, not a reason to invent facts.

## Verification order

1. `python -m unittest discover -s tests -v` checks the local software and simulated ESP32 snapshot.
2. Open `http://ESP32_IP/capture` in a browser and inspect whether the badge text is readable.
3. Run `--image` against the live Muse Spark API.
4. Run `--esp32-url` for the full hardware-to-terminal demo.

Meta Model API docs: https://dev.meta.ai/docs/quickstart and https://dev.meta.ai/docs/search-grounding
