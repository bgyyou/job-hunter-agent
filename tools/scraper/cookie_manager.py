"""
CookieManager - Cookie 管理器

功能：
- Cookie 持久化
- Cookie 加密存储
- 自动更新 Cookie
- Cookie 过期检测
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional, List
from loguru import logger
from cryptography.fernet import Fernet
import hashlib


class CookieManager:
    """
    Cookie 管理器

    管理 Cookie 的存储、加载、更新和加密
    """

    def __init__(
        self,
        platform_name: str,
        storage_dir: str = "data/cookies",
        encrypt: bool = True
    ):
        """
        初始化 Cookie 管理器

        Args:
            platform_name: 平台名称
            storage_dir: 存储目录
            encrypt: 是否加密存储
        """
        self.platform_name = platform_name
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.encrypt = encrypt

        # Cookie 文件路径
        self.cookie_file = self.storage_dir / f"{platform_name}.json"

        # Cookie 过期时间（秒）
        self.default_expiry = 7 * 24 * 3600  # 7 天

        self.logger = logger.bind(component=f"cookie_manager_{platform_name}")

        # 加密密钥
        self._key = None
        self._cipher = None

        if self.encrypt:
            self._init_encryption()

    def _init_encryption(self):
        """初始化加密"""
        key_file = self.storage_dir / ".encryption_key"

        # 如果密钥文件存在，加载密钥
        if key_file.exists():
            with open(key_file, "rb") as f:
                key = f.read()
        else:
            # 生成新密钥
            key = Fernet.generate_key()
            with open(key_file, "wb") as f:
                f.write(key)

        self._key = key
        self._cipher = Fernet(key)

        self.logger.debug("加密已初始化")

    def _encrypt_data(self, data: str) -> bytes:
        """
        加密数据

        Args:
            data: 要加密的字符串

        Returns:
            加密后的字节数据
        """
        if not self._cipher:
            return data.encode()

        return self._cipher.encrypt(data.encode())

    def _decrypt_data(self, encrypted_data: bytes) -> str:
        """
        解密数据

        Args:
            encrypted_data: 加密的字节数据

        Returns:
            解密后的字符串
        """
        if not self._cipher:
            return encrypted_data.decode()

        return self._cipher.decrypt(encrypted_data).decode()

    def save_cookies(
        self,
        cookies: Dict[str, str],
        expiry: Optional[float] = None
    ):
        """
        保存 Cookie

        Args:
            cookies: Cookie 字典
            expiry: 过期时间（秒），None 使用默认值
        """
        expiry_time = expiry or self.default_expiry

        cookie_data = {
            "cookies": cookies,
            "saved_at": time.time(),
            "expires_at": time.time() + expiry_time,
            "platform": self.platform_name
        }

        # 转换为 JSON 字符串
        json_data = json.dumps(cookie_data, ensure_ascii=False)

        try:
            if self.encrypt:
                # 加密存储
                encrypted = self._encrypt_data(json_data)
                with open(self.cookie_file, "wb") as f:
                    f.write(encrypted)
            else:
                # 明文存储
                with open(self.cookie_file, "w", encoding="utf-8") as f:
                    f.write(json_data)

            self.logger.info(f"已保存 {len(cookies)} 个 Cookie，有效期 {expiry_time / 3600:.1f} 小时")

        except Exception as e:
            self.logger.error(f"保存 Cookie 失败: {e}")

    def load_cookies(self) -> Dict[str, str]:
        """
        加载 Cookie

        Returns:
            Cookie 字典，如果不存在或过期返回空字典
        """
        if not self.cookie_file.exists():
            self.logger.debug("Cookie 文件不存在")
            return {}

        try:
            # 读取文件
            if self.encrypt:
                with open(self.cookie_file, "rb") as f:
                    encrypted_data = f.read()
                json_data = self._decrypt_data(encrypted_data)
            else:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    json_data = f.read()

            # 解析 JSON
            cookie_data = json.loads(json_data)

            # 检查过期
            expires_at = cookie_data.get("expires_at")
            if expires_at and time.time() > expires_at:
                self.logger.warning("Cookie 已过期")
                self.delete_cookies()
                return {}

            cookies = cookie_data.get("cookies", {})
            saved_at = cookie_data.get("saved_at", 0)
            remaining = int(expires_at - time.time()) if expires_at else 0

            self.logger.info(
                f"已加载 {len(cookies)} 个 Cookie，"
                f"保存时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(saved_at))}，"
                f"剩余有效期: {remaining // 3600} 小时"
            )

            return cookies

        except Exception as e:
            self.logger.error(f"加载 Cookie 失败: {e}")
            return {}

    def update_cookies(self, new_cookies: Dict[str, str]):
        """
        更新 Cookie

        Args:
            new_cookies: 新的 Cookie
        """
        current_cookies = self.load_cookies()
        current_cookies.update(new_cookies)
        self.save_cookies(current_cookies)
        self.logger.debug(f"更新了 {len(new_cookies)} 个 Cookie")

    def delete_cookies(self):
        """删除 Cookie"""
        if self.cookie_file.exists():
            self.cookie_file.unlink()
            self.logger.info("Cookie 已删除")

    def is_expired(self) -> bool:
        """
        检查 Cookie 是否过期

        Returns:
            是否过期
        """
        if not self.cookie_file.exists():
            return True

        try:
            if self.encrypt:
                with open(self.cookie_file, "rb") as f:
                    encrypted_data = f.read()
                json_data = self._decrypt_data(encrypted_data)
            else:
                with open(self.cookie_file, "r", encoding="utf-8") as f:
                    json_data = f.read()

            cookie_data = json.loads(json_data)
            expires_at = cookie_data.get("expires_at")

            if expires_at:
                return time.time() > expires_at

            return False

        except Exception as e:
            self.logger.error(f"检查 Cookie 过期状态失败: {e}")
            return True

    def get_cookie(self, name: str) -> Optional[str]:
        """
        获取指定的 Cookie

        Args:
            name: Cookie 名称

        Returns:
            Cookie 值，不存在返回 None
        """
        cookies = self.load_cookies()
        return cookies.get(name)

    def has_cookie(self, name: str) -> bool:
        """
        检查 Cookie 是否存在

        Args:
            name: Cookie 名称

        Returns:
            是否存在
        """
        return self.get_cookie(name) is not None

    def get_all_cookies(self) -> List[Dict[str, str]]:
        """
        获取所有 Cookie（格式化为 requests 兼容格式）

        Returns:
            Cookie 列表
        """
        cookies = self.load_cookies()
        return [{"name": k, "value": v} for k, v in cookies.items()]

    def export_cookies(self, filepath: Optional[Path] = None) -> str:
        """
        导出 Cookie 到文件

        Args:
            filepath: 导出路径，None 使用默认路径

        Returns:
            导出文件路径
        """
        cookies = self.load_cookies()

        if not filepath:
            filepath = self.storage_dir / f"{self.platform_name}_export_{int(time.time())}.json"

        export_data = {
            "platform": self.platform_name,
            "exported_at": time.time(),
            "cookies": cookies
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Cookie 已导出到: {filepath}")
        return str(filepath)

    def import_cookies(self, filepath: Path):
        """
        从文件导入 Cookie

        Args:
            filepath: 文件路径
        """
        with open(filepath, "r", encoding="utf-8") as f:
            import_data = json.load(f)

        cookies = import_data.get("cookies", {})
        self.save_cookies(cookies)
        self.logger.info(f"从 {filepath} 导入了 {len(cookies)} 个 Cookie")

    def get_cookie_string(self) -> str:
        """
        获取 Cookie 字符串（用于浏览器）

        Returns:
            Cookie 字符串
        """
        cookies = self.load_cookies()
        return "; ".join([f"{k}={v}" for k, v in cookies.items()])

    def __repr__(self) -> str:
        return f"CookieManager(platform={self.platform_name}, has_cookies={self.cookie_file.exists()})"