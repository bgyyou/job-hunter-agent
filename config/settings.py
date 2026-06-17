from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import os
from pathlib import Path

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

class Settings(BaseSettings):
    """配置管理 - 支持从 .env 文件加载"""

    # ==================== 火山引擎 API 配置 ====================
    volcano_api_key: str = Field("", env="VOLCANO_API_KEY")
    volcano_coding_api_url: str = Field("", env="VOLCANO_CODING_API_URL")
    volcano_chat_api_url: str = Field("", env="VOLCANO_CHAT_API_URL")
    volcano_model: str = Field("", env="VOLCANO_MODEL")
    volcano_use_coding_api: str = Field("false", env="VOLCANO_USE_CODING_API")
    volcano_use_anthropic_format: bool = Field(True, env="VOLCANO_USE_ANTHROPIC_FORMAT")

    # ==================== Anthropic API 配置 ====================
    anthropic_api_key: str = Field("your_api_key_here", env="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-3-sonnet-20240229", env="ANTHROPIC_MODEL")
    max_tokens: int = Field(4096, env="MAX_TOKENS")

    # ==================== 招聘平台配置 ====================
    boss_cookies_file: str = Field(
        str(PROJECT_ROOT / "data" / "cookies" / "boss.json"),
        env="BOSS_COOKIES_FILE"
    )
    boss_login_url: str = Field("https://login.zhipin.com", env="BOSS_LOGIN_URL")

    liepin_cookies_file: str = Field(
        str(PROJECT_ROOT / "data" / "cookies" / "liepin.json"),
        env="LIEPIN_COOKIES_FILE"
    )
    liepin_login_url: str = Field("https://www.liepin.com", env="LIEPIN_LOGIN_URL")

    jobsdb_cookies_file: str = Field(
        str(PROJECT_ROOT / "data" / "cookies" / "jobsdb.json"),
        env="JOBSDB_COOKIES_FILE"
    )
    jobsdb_login_url: str = Field("https://hk.jobsdb.com", env="JOBSDB_LOGIN_URL")

    # ==================== 爬虫配置 ====================
    request_delay_min: float = Field(1.0, env="REQUEST_DELAY_MIN")
    request_delay_max: float = Field(3.0, env="REQUEST_DELAY_MAX")
    max_concurrent_jobs: int = Field(10, env="MAX_CONCURRENT_JOBS")
    headless_browser: bool = Field(True, env="HEADLESS_BROWSER")
    browser_profile_dir: str = Field(
        str(PROJECT_ROOT / "data" / "browser_profiles"),
        env="BROWSER_PROFILE_DIR"
    )

    # ==================== 爬虫策略配置 ====================
    crawler_rate_limit_min: float = Field(2.0, env="CRAWLER_RATE_LIMIT_MIN")
    crawler_rate_limit_max: float = Field(5.0, env="CRAWLER_RATE_LIMIT_MAX")
    crawler_daily_limit: int = Field(200, env="CRAWLER_DAILY_LIMIT")
    crawler_blocked_timeout_minutes: int = Field(30, env="CRAWLER_BLOCKED_TIMEOUT_MIN")
    crawler_max_retries: int = Field(3, env="CRAWLER_MAX_RETRIES")
    crawler_timeout: int = Field(30, env="CRAWLER_TIMEOUT")
    crawler_concurrent_domains: int = Field(3, env="CRAWLER_CONCURRENT_DOMAINS")

    # ==================== 爬虫 Edge 复用配置 ====================
    crawler_edge_user_data: Optional[str] = Field(None, env="CRAWLER_EDGE_USER_DATA")
    crawler_edge_profile: str = Field("Default", env="CRAWLER_EDGE_PROFILE")

    def edge_user_data_dir(self) -> Optional[str]:
        """Resolve Edge user-data directory.

        Priority:
          1. Explicit env var CRAWLER_EDGE_USER_DATA
          2. Auto-detect from %LOCALAPPDATA%\\Microsoft\\Edge\\User Data
        """
        if self.crawler_edge_user_data:
            return self.crawler_edge_user_data
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
        return None

    # ==================== 缓存配置 ====================
    cache_enabled: bool = Field(True, env="CACHE_ENABLED")
    cache_ttl: int = Field(3600, env="CACHE_TTL")  # 1 小时
    cache_dir: str = Field(str(PROJECT_ROOT / "data" / "cache"), env="CACHE_DIR")

    # ==================== 日志配置 ====================
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_dir: str = Field(str(PROJECT_ROOT / "logs"), env="LOG_DIR")
    log_file: str = Field("job_hunter.log", env="LOG_FILE")

    # ==================== 投递配置 ====================
    auto_apply_threshold: int = Field(85, env="AUTO_APPLY_THRESHOLD")
    manual_confirm_min: int = Field(70, env="MANUAL_CONFIRM_MIN")

    # ==================== 性能配置 ====================
    llm_concurrency: int = Field(5, env="LLM_CONCURRENCY")
    max_context_tokens: int = Field(100000, env="MAX_CONTEXT_TOKENS")
    context_compress_threshold: int = Field(80000, env="CONTEXT_COMPRESS_THRESHOLD")

    # ==================== 数据库配置 ====================
    db_path: str = Field(
        str(PROJECT_ROOT / "data" / "jobhunter_v2.db"),
        env="DB_PATH"
    )

    class Config:
        env_file = str(PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    def ensure_directories(self):
        """确保所有需要的目录存在"""
        directories = [
            Path(self.cache_dir),
            Path(self.log_dir),
            Path(self.browser_profile_dir),
            PROJECT_ROOT / "data" / "cookies",
            PROJECT_ROOT / "data" / "resumes",
            PROJECT_ROOT / "data" / "jobs",
            PROJECT_ROOT / "data" / "reports",
            PROJECT_ROOT / "data" / "context",
            PROJECT_ROOT / "tests" / "unit",
            PROJECT_ROOT / "tests" / "integration",
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> str:
        """获取完整日志路径"""
        return str(Path(self.log_dir) / self.log_file)

# 全局配置实例
settings = Settings()

# 确保目录存在
settings.ensure_directories()