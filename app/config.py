from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://data_ai:data_ai_dev_password@localhost:5432/income_assistant?options=-csearch_path%3Ddata_ai"
    storage_dir: Path = Path("./storage")
    max_file_mb: int = 20
    max_files_per_case: int = 10
    max_pdf_pages: int = 60
    max_csv_rows: int = 3000
    ocr_lang: str = "vie+eng"
    internal_service_token: str = ""
    export_dir: Path = Path("./exports")
    export_max_rows_per_sheet: int = 50000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
settings.export_dir.mkdir(parents=True, exist_ok=True)
