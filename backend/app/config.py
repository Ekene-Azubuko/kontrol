"""Environment configuration shared by the API and worker."""

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
    creao_poll_seconds: float = 5
    worker_interval: float = 1
    mock_agent_seconds: float = 3
    dispatch_stage_seconds: float = 12
    live_simulation_enabled: bool = False
    demo_fleet_enabled: bool = False


settings = Settings()
if settings.app_env == "production" and settings.demo_auth:
    raise RuntimeError("DEMO_AUTH must be false in production")
