"""Environment configuration shared by the API and worker."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Keep deployment and integration configuration outside source code."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./kontrol.db"
    app_env: str = "development"
    demo_auth: bool = True
    creao_mode: str = "mock"
    creao_base_url: str = ""
    creao_api_key: str = ""
    creao_api_version: str = ""
    creao_invoke_path: str = ""
    creao_poll_path: str = ""
    creao_intake_agent_id: str = ""
    creao_hospital_agent_id: str = ""
    creao_dispatch_agent_id: str = ""
    creao_planning_agent_id: str = ""
    creao_input_field: str = "context"
    creao_timeout: int = 180
    creao_poll_seconds: float = Field(default=2, ge=1, allow_inf_nan=False)
    worker_interval: float = 1
    mock_agent_seconds: float = 3
    live_simulation_enabled: bool = False
    demo_fleet_enabled: bool = False
    transcription_mode: str = "mock"
    transcription_api_key: str = ""
    transcription_base_url: str = "https://api.openai.com/v1"
    transcription_model: str = "gpt-4o-mini-transcribe"
    transcription_timeout: float = 60
    call_audio_dir: str = "/app/call_audio"
    call_max_audio_bytes: int = 20 * 1024 * 1024
    call_max_duration_seconds: float = 300
    call_geocoding_url: str = "https://photon.komoot.io/api/"
    call_intersections_url: str = "https://data.sf.gov/resource/gmfx-8h6i.json"
    telephony_enabled: bool = False
    telephony_public_url: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    twilio_phone_number: str = ""
    twilio_record_calls: bool = False
    live_transcription_api_key: str = ""
    live_transcription_model: str = "gpt-live-transcribe"
    live_transcription_url: str = "wss://api.openai.com/v1/realtime?intent=transcription"
    live_finalization_timeout: int = 30


settings = Settings()
if settings.app_env == "production" and settings.demo_auth:
    raise RuntimeError("DEMO_AUTH must be false in production")
