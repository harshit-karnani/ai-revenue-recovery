from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    ANTHROPIC_API_KEY: Optional[str] = None
    ML_CONFIDENCE_THRESHOLD: float = 0.75
    ENVIRONMENT: str = "development"
    
    # LLM Config
    LLM_PROVIDER: str = "mock"
    GEMINI_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gemini-2.5-flash"
    LLM_BASE_URL: Optional[str] = None
    LLM_TIMEOUT_SECONDS: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
