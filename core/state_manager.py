# core/state_manager.py
from typing import Dict, Any, List, Optional
import json
from pathlib import Path
from loguru import logger


class StateManager:
    """状态管理器 - 可靠性：持久化状态"""

    def __init__(self, storage_dir: str = "data/agent_states"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger.bind(component="state_manager")

    def save_state(self, key: str, state: Dict[str, Any]):
        """
        保存状态

        Args:
            key: 状态键
            state: 状态数据
        """
        state_file = self.storage_dir / f"{key}.json"

        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"状态已保存: {key}")
        except Exception as e:
            self.logger.error(f"保存状态失败 {key}: {e}")
            raise

    def load_state(self, key: str) -> Optional[Dict[str, Any]]:
        """
        加载状态

        Args:
            key: 状态键

        Returns:
            状态数据，不存在返回 None
        """
        state_file = self.storage_dir / f"{key}.json"

        if not state_file.exists():
            self.logger.debug(f"状态不存在: {key}")
            return None

        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.logger.debug(f"状态已加载: {key}")
            return state
        except Exception as e:
            self.logger.error(f"加载状态失败 {key}: {e}")
            return None

    def delete_state(self, key: str):
        """
        删除状态

        Args:
            key: 状态键
        """
        state_file = self.storage_dir / f"{key}.json"

        if state_file.exists():
            state_file.unlink()
            self.logger.debug(f"状态已删除: {key}")

    def list_states(self) -> List[str]:
        """
        列出所有状态

        Returns:
            状态键列表
        """
        states = []
        for state_file in self.storage_dir.glob("*.json"):
            states.append(state_file.stem)
        return sorted(states)

    def state_exists(self, key: str) -> bool:
        """
        检查状态是否存在

        Args:
            key: 状态键

        Returns:
            是否存在
        """
        state_file = self.storage_dir / f"{key}.json"
        return state_file.exists()