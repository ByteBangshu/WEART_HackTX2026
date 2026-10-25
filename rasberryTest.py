from gpiozero import LED
from time import sleep

# Assumes your LED is connected to GPIO 4
led = LED(4)

print("Starting GPIO test. Press Ctrl+C to stop.")

try:
    while True:
        led.on()
        print("LED is ON")
        sleep(1)
        led.off()
        print("LED is OFF")
        sleep(1)
except KeyboardInterrupt:
    print("\nTest stopped by user.")
    led.close()