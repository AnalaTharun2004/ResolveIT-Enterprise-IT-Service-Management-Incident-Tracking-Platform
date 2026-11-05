import os


class Settings:
    app_name = "ResolveIT"
    api_prefix = "/api/v1"
    secret_key = os.getenv(
        "RESOLVEIT_SECRET_KEY",
        "local-development-only-change-this-secret-before-deployment",
    )
    algorithm = "HS256"
    access_token_minutes = int(os.getenv("RESOLVEIT_ACCESS_TOKEN_MINUTES", "60"))
    database_url = os.getenv("RESOLVEIT_DATABASE_URL", "sqlite:///./resolveit.db")
    ai_base_url = os.getenv("RESOLVEIT_AI_BASE_URL", "").rstrip("/")
    ai_api_key = os.getenv("RESOLVEIT_AI_API_KEY", "")
    ai_model = os.getenv("RESOLVEIT_AI_MODEL", "gpt-4o-mini")


settings = Settings()
