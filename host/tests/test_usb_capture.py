import pytest

from tools.esp32_usb_capture import read_jpeg


class FakeSerial:
    def __init__(self, lines, payload=b""):
        self.lines = iter(lines)
        self.payload = payload

    def readline(self):
        return next(self.lines, b"")

    def read(self, size):
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk


def test_read_jpeg_accepts_complete_raw_serial_frame():
    image = b"\xff\xd8\xff\xd9"
    port = FakeSerial([b"WEART_USB_JPEG 4\r\n", b"\r\nWEART_USB_END\r\n"], image)

    assert read_jpeg(port, 1) == image


@pytest.mark.parametrize(
    ("header", "trailer", "payload", "error"),
    [
        (b"WEART_USB_JPEG 4\r\n", b"missing\r\n", b"\xff\xd8\xff\xd9", "trailer was missing"),
        (b"WEART_USB_JPEG 4\r\n", b"WEART_USB_END\r\n", b"bad!", "complete JPEG"),
        (b"WEART_USB_JPEG 3000001\r\n", b"", b"", "invalid JPEG length"),
    ],
)
def test_read_jpeg_rejects_bad_frames(header, trailer, payload, error):
    port = FakeSerial([header, trailer], payload)

    with pytest.raises((TimeoutError, ValueError), match=error):
        read_jpeg(port, 1)
