# core/cache.py
from typing import Any, Optional
import json
import time
from pathlib import Path
from loguru import logger


class Cache:
    """缓存系统 - 效率"""

    def __init__(self, cache_dir: str = "data/cache", default_ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl
        self.logger = logger.bind(component="cache")

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在或过期返回 None
        """
        cache_file = self.cache_dir / f"{key}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 检查是否过期
            if data.get("expires_at") and time.time() > data["expires_at"]:
                cache_file.unlink()
                self.logger.debug(f"缓存已过期: {key}")
                return None

            return data["value"]

        except Exception as e:
            self.logger.error(f"读取缓存失败 {key}: {e}")
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None 表示使用默认值
        """
        cache_file = self.cache_dir / f"{key}.json"

        expires_at = None
        ttl = ttl or self.default_ttl
        if ttl > 0:
            expires_at = time.time() + ttl

        data = {
            "value": value,
            "expires_at": expires_at,
            "created_at": time.time()
        }

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            self.logger.debug(f"缓存已设置: {key}, TTL: {ttl}s")
        except Exception as e:
            self.logger.error(f"写入缓存失败 {key}: {e}")

    def delete(self, key: str):
        """
        删除缓存

        Args:
            key: 缓存键
        """
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            cache_file.unlink()
            self.logger.debug(f"缓存已删除: {key}")

    def clear(self):
        """清空所有缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        self.logger.debug("缓存已清空")

    def cleanup_expired(self):
        """清理过期缓存"""
        cleaned = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if data.get("expires_at") and time.time() > data["expires_at"]:
                    cache_file.unlink()
                    cleaned += 1

            except Exception as e:
                self.logger.error(f"清理缓存失败 {cache_file}: {e}")

        if cleaned > 0:
            self.logger.info(f"清理了 {cleaned} 个过期缓存")