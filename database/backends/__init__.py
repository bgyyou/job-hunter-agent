"""Abstract base class for all database backends."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseBackend(ABC):
    """All database backends must implement these methods."""

    @abstractmethod
    def insert_resume(self, data: Dict) -> str:
        pass

    @abstractmethod
    def get_resume(self, resume_id: str) -> Optional[Dict]:
        pass

    @abstractmethod
    def list_resumes(self, user_id: str = "default") -> List[Dict]:
        pass

    @abstractmethod
    def soft_delete_resume(self, resume_id: str) -> None:
        pass

    @abstractmethod
    def insert_jd(self, data: Dict) -> str:
        pass

    @abstractmethod
    def get_jd(self, jd_id: str) -> Optional[Dict]:
        pass

    @abstractmethod
    def list_jds(self, user_id: str = "default", source: Optional[str] = None, limit: int = 100) -> List[Dict]:
        pass

    @abstractmethod
    def get_jd_by_url(self, url: str, user_id: str = "default") -> Optional[Dict]:
        pass

    @abstractmethod
    def search_jds(self, keyword: str, industry_tag: Optional[str] = None,
                   function_tag: Optional[str] = None, position_tag: Optional[str] = None,
                   user_id: str = "default", limit: int = 50) -> List[Dict]:
        pass

    @abstractmethod
    def soft_delete_jd(self, jd_id: str) -> None:
        pass

    @abstractmethod
    def insert_match(self, data: Dict) -> str:
        pass

    @abstractmethod
    def list_matches(self, resume_id: Optional[str] = None, jd_id: Optional[str] = None,
                     user_id: str = "default", limit: int = 100) -> List[Dict]:
        pass

    @abstractmethod
    def insert_optimization(self, data: Dict) -> str:
        pass

    @abstractmethod
    def list_optimizations(self, jd_id: Optional[str] = None, user_id: str = "default") -> List[Dict]:
        pass

    @abstractmethod
    def update_optimization_adopted(self, opt_id: str, adopted: int) -> None:
        pass

    @abstractmethod
    def insert_chunk(self, data: Dict) -> str:
        pass

    @abstractmethod
    def insert_chunks_batch(self, jd_id: str, chunks: List[Dict]) -> List[str]:
        pass

    @abstractmethod
    def get_chunks_by_jd(self, jd_id: str) -> List[Dict]:
        pass

    @abstractmethod
    def insert_quality_check(self, data: Dict) -> int:
        pass

    @abstractmethod
    def list_quality_checks(self, check_type: Optional[str] = None,
                            target_table: Optional[str] = None, limit: int = 100) -> List[Dict]:
        pass

    @abstractmethod
    def get_stats(self) -> Dict:
        pass

    @abstractmethod
    def search_similar_chunks(self, query_text: str, top_k: int = 5,
                              filter_chunk_type: Optional[str] = None,
                              user_id: Optional[str] = None) -> List[Dict]:
        pass
