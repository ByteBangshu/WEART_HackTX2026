import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "mock"
    model: str = "muse-spark-1.3"
    pin: str = Field(min_length=10)
    device_token: str = ""
    device_id: str = "badge-camera"
    device_registry: str = ""
    origin: str = "http://127.0.0.1:8765"
    api_key: str = ""
    ttl_seconds: int = Field(default=1800, ge=30, le=86400)
    job_timeout: float = Field(default=60, gt=0, le=120)
    stage_timeout: float = Field(default=18, gt=0, le=60)
    rate_seconds: float = Field(default=5, ge=0)
    max_jobs: int = Field(default=50, ge=1, le=500)
    max_active: int = Field(default=2, ge=1, le=8)
    require_confirmation: bool = False
    allow_unbounded_search: bool = False
    kill_switch: bool = False
    job_cost_cap: float = Field(default=0.25, gt=0)
    daily_cost_cap: float = Field(default=5, gt=0)
    max_search_calls: int = Field(default=6, ge=1, le=6)
    mock_delay: float = Field(default=0.25, ge=0, le=5)
    tls_cert: str = ""
    tls_key: str = ""
    bind: str = "127.0.0.1"
    port: int = 8765

    @model_validator(mode="after")
    def safe(self):
        if self.provider not in {"mock", "meta"}:
            raise ValueError("provider must be mock or meta")
        if self.model not in {"muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"}:
            raise ValueError("only verified Standard mode models are permitted")
        if self.provider == "meta" and not self.api_key:
            raise ValueError("MODEL_API_KEY is required for live mode")
        if self.device_token and len(self.device_token) < 32:
            raise ValueError("device token needs at least 32 characters")
        if self.bind in {"0.0.0.0", "::"}:
            raise ValueError("bind to an explicit private LAN address or loopback")
        if self.bind not in {"127.0.0.1", "localhost", "::1"}:
            import ipaddress

            if not ipaddress.ip_address(self.bind).is_private:
                raise ValueError("host must use a private LAN address")
            if not self.tls_cert or not self.tls_key or not self.origin.startswith("https://"):
                raise ValueError("LAN serving requires TLS and an HTTPS origin")
        return self

    @classmethod
    def load(cls):
        path = os.getenv("WEART_CONFIG")
        data = yaml.safe_load(Path(path).read_text()) if path else {}
        data = data or {}
        for key in cls.model_fields:
            value = os.getenv("MODEL_API_KEY" if key == "api_key" else "WEART_" + key.upper())
            if value is not None:
                data[key] = value
        return cls.model_validate(data)
