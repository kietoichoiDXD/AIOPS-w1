from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "finops-watch-ai-engine"
    app_version: str = "1.0.0"
    debug: bool = False


    mock_anomaly_probability: float = 0.80
    mock_max_anomalies: int = 3
    clock_skew_tolerance_seconds: int = 300


    rate_limit_per_min: int = 100


    error_budget_lock_threshold_prod: float = 1.0
    error_budget_lock_threshold_staging: float = 10.0


    mock_s3_audit_status: str = "connected"
    mock_bedrock_status: str = "accessible"
    mock_s3_cur_status: str = "reachable"


settings = Settings()
