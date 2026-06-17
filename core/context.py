# core/context.py
from typing import Dict, List, Optional
from datetime import datetime
import pickle
import hashlib
from pathlib import Path
from loguru import logger


class ContextManager:
    """上下文管理器 - 控制 Agent 的"记忆" """

    def __init__(self, max_tokens: int = 100000, persistence_dir: str = "data/context"):
        self.max_tokens = max_tokens
        self.persistence_dir = Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, Dict] = {}

    def create_session(self, user_id: str) -> str:
        """
        创建新会话

        Args:
            user_id: 用户 ID

        Returns:
            会话 ID
        """
        session_id = self._generate_session_id(user_id)
        self.sessions[session_id] = {
            "user_id": user_id,
            "created_at": datetime.now().isoformat(),
            "messages": [],
            "state": {},
            "token_count": 0
        }
        logger.info(f"创建会话: {session_id}")
        return session_id

    def add_message(self, session_id: str, role: str, content: str,
                   metadata: Optional[Dict] = None):
        """
        添加消息到上下文

        Args:
            session_id: 会话 ID
            role: 角色（system/user/assistant）
            content: 内容
            metadata: 元数据
        """
        session = self._get_session(session_id)

        # 估算 Token 数
        token_count = self._estimate_tokens(content)

        # 检查是否超限
        if session["token_count"] + token_count > self.max_tokens:
            logger.warning(f"上下文接近上限，尝试压缩...")
            self.compress_context(session_id)

        # 添加消息
        message = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
            "token_count": token_count
        }
        session["messages"].append(message)
        session["token_count"] += token_count

        # 自动持久化
        self._save_session(session_id)

    def get_context(self, session_id: str, max_tokens: Optional[int] = None) -> str:
        """
        获取用于 LLM 的上下文文本

        Args:
            session_id: 会话 ID
            max_tokens: 最大 Token 数

        Returns:
            上下文文本
        """
        session = self._get_session(session_id)
        limit = max_tokens or self.max_tokens

        # 构建上下文
        context_parts = []
        current_tokens = 0

        # 从最近的消息开始
        for msg in reversed(session["messages"]):
            if current_tokens + msg["token_count"] > limit:
                break

            context_parts.insert(0, f"{msg['role']}: {msg['content']}")
            current_tokens += msg["token_count"]

        return "\n".join(context_parts)

    def compress_context(self, session_id: str, strategy: str = "keep_recent"):
        """
        压缩上下文

        Args:
            session_id: 会话 ID
            strategy: 压缩策略
        """
        session = self._get_session(session_id)

        if strategy == "keep_recent":
            # 只保留最近的消息
            session["messages"] = session["messages"][-10:]
            session["token_count"] = sum(m["token_count"] for m in session["messages"])

        elif strategy == "keep_important":
            # 保留重要消息
            important = [
                m for m in session["messages"]
                if m.get("metadata", {}).get("important", False)
            ]
            recent = session["messages"][-5:]

            session["messages"] = important + recent
            session["token_count"] = sum(m["token_count"] for m in session["messages"])

        logger.info(f"压缩上下文: {session_id}, 策略: {strategy}")

    def _estimate_tokens(self, text: str) -> int:
        """
        估算 Token 数

        Args:
            text: 文本

        Returns:
            Token 数
        """
        if not text:
            return 0

        total = 0

        for char in text:
            # 中文字符
            if '一' <= char <= '鿿':
                total += 1.5
            # 英文字母/数字
            elif char.isalnum() or char in ' .,!?-':
                total += 0.25
            else:
                total += 0.5

        return int(total)

    def _save_session(self, session_id: str):
        """持久化会话"""
        session_path = self.persistence_dir / f"{session_id}.pkl"
        with open(session_path, "wb") as f:
            pickle.dump(self.sessions[session_id], f)

    def _load_session(self, session_id: str) -> Optional[Dict]:
        """加载持久化的会话"""
        session_path = self.persistence_dir / f"{session_id}.pkl"

        if session_path.exists():
            with open(session_path, "rb") as f:
                return pickle.load(f)
        return None

    def _get_session(self, session_id: str) -> Dict:
        """获取会话"""
        if session_id not in self.sessions:
            # 尝试从持久化加载
            loaded = self._load_session(session_id)
            if loaded:
                self.sessions[session_id] = loaded
            else:
                raise ValueError(f"会话不存在: {session_id}")

        return self.sessions[session_id]

    def _generate_session_id(self, user_id: str) -> str:
        """生成会话 ID"""
        timestamp = datetime.now().isoformat()
        raw = f"{user_id}_{timestamp}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]