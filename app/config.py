from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/platform_gc"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "HS256"

    # OTP
    OTP_EXPIRE_SECONDS: int = 300
    OTP_MAX_REQUESTS: int = 3
    OTP_RATE_WINDOW_SECONDS: int = 600

    # Coins
    COINS_EARN_RATE: float = 5.0            # coins per ₹100 spent
    COIN_RUPEE_VALUE: float = 0.10          # 1 coin = ₹0.10
    MAX_COINS_REDEEM_PERCENT: float = 0.20  # max 20% of order via coins
    COINS_EXPIRY_DAYS: int = 365
    EXPIRY_NOTIFY_DAYS: int = 7

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
