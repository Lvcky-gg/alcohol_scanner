import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    flask_run_port: int
    project_root: Path

    @classmethod
    def from_env(cls) -> "Settings":
        project_root = Path(__file__).resolve().parent.parent
        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", "5432")),
            db_name=os.getenv("DB_NAME", "app_db"),
            db_user=os.getenv("DB_USER", "app_user"),
            db_password=os.getenv("DB_PASSWORD", "app_password"),
            flask_run_port=int(os.getenv("FLASK_RUN_PORT", "5000")),
            project_root=project_root,
        )
