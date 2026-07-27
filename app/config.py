from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DES Unstructured Data Catalog"
    app_env: str = "development"
    data_dir: Path = Path("data")
    uploads_dir: Path = Path("uploads")
    sqlite_path: Path = Path("data/documents.db")
    chroma_path: Path = Path("data/chroma")
    chroma_collection: str = "des_unstructured_documents"
    anthropic_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_path.mkdir(parents=True, exist_ok=True)
