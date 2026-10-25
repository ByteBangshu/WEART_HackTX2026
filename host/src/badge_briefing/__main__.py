import uvicorn

from .app import create_app
from .config import Settings


def main():
    try:
        settings = Settings.load()
    except ValueError:
        raise SystemExit(
            "Invalid WEART configuration. Check required passphrase, Standard model, provider key and LAN TLS settings; values are withheld."
        ) from None
    uvicorn.run(
        create_app(settings),
        host=settings.bind,
        port=settings.port,
        ssl_certfile=settings.tls_cert or None,
        ssl_keyfile=settings.tls_key or None,
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
