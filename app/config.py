from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str = ""
    gemini_api_key: str = ""
    database_url: str = ""
    webhook_url: str = ""
    allowed_chat_id: int | None = None
    gemini_model: str = "gemini-3.5-flash"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
