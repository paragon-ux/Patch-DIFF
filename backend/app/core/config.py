import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("PATCHDIFF_APP_NAME", "PatchDIFF MVP")
    environment: str = os.getenv("PATCHDIFF_ENV", "local")
    database_url: str = os.getenv(
        "PATCHDIFF_DATABASE_URL",
        "postgresql+psycopg://patchdiff:patchdiff@localhost:5432/patchdiff",
    )


settings = Settings()

