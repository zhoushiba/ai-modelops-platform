"""全局配置。

所有配置都可通过环境变量覆盖（见仓库根目录 ``.env.example``）。
本地默认值面向"开箱即用"：SQLite + 本地磁盘存储 + 单机线程池。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录，作为所有相对路径的基准
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """应用配置（环境变量优先，其次 .env，最后默认值）。"""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "AI ModelOps Platform"
    app_version: str = "1.0.0"
    env: str = "dev"
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # --- 数据库 -----------------------------------------------------------
    # sqlite:///./data/app.db | mysql+pymysql://user:pwd@host:3306/db | postgresql+psycopg://...
    database_url: str = "sqlite:///./data/app.db"
    db_echo: bool = False

    # --- 存储 -------------------------------------------------------------
    storage_dir: str = "./storage"
    max_upload_mb: int = 20

    # --- 认证 -------------------------------------------------------------
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # --- 训练执行器 -------------------------------------------------------
    training_inline: bool = False  # True 时同步执行（测试用）
    worker_concurrency: int = 2
    worker_poll_seconds: float = 0.2
    seed_samples: bool = True

    # --- 推理网关默认配额 -------------------------------------------------
    rate_limit_per_min: int = 60
    rate_limit_burst: int = 10
    token_quota: int = 200_000

    # --- 可选：真实上游大模型（OpenAI 兼容） -------------------------------
    # 留空则 Prompt 实验使用本地抽取式引擎
    upstream_llm_base_url: str = ""
    upstream_llm_api_key: str = ""
    upstream_llm_model: str = "gpt-4o-mini"
    upstream_timeout_seconds: float = 30.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    # --- 派生路径 ---------------------------------------------------------
    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        return p if p.is_absolute() else (BACKEND_DIR / p)

    @property
    def data_path(self) -> Path:
        return BACKEND_DIR / "data"

    @property
    def samples_path(self) -> Path:
        return BACKEND_DIR / "samples"

    @property
    def models_path(self) -> Path:
        return self.storage_path / "models"

    @property
    def datasets_path(self) -> Path:
        return self.storage_path / "datasets"

    @property
    def eval_path(self) -> Path:
        return self.storage_path / "eval"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_dirs(self) -> None:
        """创建所有运行时目录（幂等）。"""
        for path in (self.data_path, self.storage_path, self.models_path, self.datasets_path, self.eval_path):
            path.mkdir(parents=True, exist_ok=True)

    def absolute_path(self, relative: str) -> Path:
        """把数据库里保存的相对路径还原成绝对路径。"""
        path = Path(relative)
        return path if path.is_absolute() else (BACKEND_DIR / path)

    def relative_path(self, path: Path) -> str:
        """把绝对路径转换成相对 backend/ 的可移植路径。"""
        try:
            return path.resolve().relative_to(BACKEND_DIR.resolve()).as_posix()
        except ValueError:
            return str(path)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
