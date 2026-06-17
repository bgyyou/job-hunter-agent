"""JD auto-classifier: Rule + Embedding + LLM fallback (Layer 1/2/3)."""

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger


# ---------------------------------------------------------------------------
# Utility: lightweight embedding via TF-IDF (no external dependency)
# ---------------------------------------------------------------------------

class _SimpleVectorizer:
    """Minimal bag-of-words TF-IDF vectorizer. No pip install required."""

    def __init__(self):
        self.vocab: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self._doc_count = 0

    def _tokenize(self, text: str) -> List[str]:
        # Simple Chinese/English tokenization: split on non-alphanumeric
        import re
        return re.findall(r'[a-zA-Z0-9]+|[一-鿿]', text.lower())

    def fit(self, texts: List[str]):
        df: Dict[str, int] = {}
        self._doc_count = len(texts)
        for text in texts:
            tokens = set(self._tokenize(text))
            for t in tokens:
                df[t] = df.get(t, 0) + 1
        self.vocab = {w: i for i, w in enumerate(sorted(df.keys()))}
        dim = len(self.vocab)
        self.idf = {w: math.log((self._doc_count + 1) / (df.get(w, 0) + 1)) + 1 for w in self.vocab}

    def transform(self, text: str) -> List[float]:
        tokens = self._tokenize(text)
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        dim = len(self.vocab)
        vec = [0.0] * dim
        for w, cnt in tf.items():
            idx = self.vocab.get(w)
            if idx is not None:
                vec[idx] = cnt * self.idf.get(w, 1.0)
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def cosine(a: List[float], b: List[float]) -> float:
        if len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class Classifier:
    """Three-layer JD classifier: Rule → Embedding → LLM fallback."""

    def __init__(self, taxonomy_path: Optional[str] = None):
        if taxonomy_path is None:
            taxonomy_path = str(Path(__file__).parent.parent / "data" / "job_taxonomy.json")
        self.taxonomy = json.loads(Path(taxonomy_path).read_text(encoding="utf-8"))
        self._build_flat_positions()
        self.vectorizer = _SimpleVectorizer()
        self._vectorized = False

    def _build_flat_positions(self):
        """Build flat lookup: position_name → (industry, function)."""
        self.position_map: Dict[str, Tuple[str, str]] = {}
        self.all_position_names: List[str] = []
        for industry, funcs in self.taxonomy.get("categories", {}).items():
            for func_name, positions in funcs.get("职能", {}).items():
                for pos in positions.get("岗位", []):
                    self.position_map[pos] = (industry, func_name)
                    self.all_position_names.append(pos)
        logger.info(
            f"Loaded taxonomy: {len(self.position_map)} positions across "
            f"{len(self.taxonomy['categories'])} industries"
        )

    def _ensure_vectorized(self):
        if not self._vectorized:
            self.vectorizer.fit(self.all_position_names)
            self._position_vectors = {
                pos: self.vectorizer.transform(pos) for pos in self.all_position_names
            }
            self._vectorized = True

    def classify(self, title: str, raw_text: str = "") -> Dict[str, Optional[str]]:
        """
        Classify a JD into (industry_tag, function_tag, position_tag).
        Falls back through 3 layers.
        Returns: {"industry_tag": ..., "function_tag": ..., "position_tag": ..., "layer": 1|2|3}
        """
        # --- Layer 1: Rule matching ---
        result = self._layer1_rule(title, raw_text)
        if result:
            result["layer"] = 1
            return result

        # --- Layer 2: Embedding similarity ---
        result = self._layer2_embedding(title, raw_text)
        if result:
            result["layer"] = 2
            return result

        # --- Layer 3: LLM fallback (lazy import to avoid circular deps) ---
        return self._layer3_llm(title, raw_text)

    def _layer1_rule(self, title: str, raw_text: str) -> Optional[Dict]:
        """Layer 1: Exact keyword match against taxonomy leaf nodes."""
        text = title + " " + raw_text[:200]
        # Try longest-first to prefer specific matches
        candidates = sorted(self.position_map.keys(), key=len, reverse=True)
        for pos in candidates:
            if pos in text:
                industry, func = self.position_map[pos]
                return {
                    "industry_tag": industry,
                    "function_tag": func,
                    "position_tag": pos,
                }
        return None

    def _layer2_embedding(self, title: str, raw_text: str) -> Optional[Dict]:
        """Layer 2: TF-IDF cosine similarity against all position names."""
        self._ensure_vectorized()
        query_vec = self.vectorizer.transform(title + " " + raw_text[:200])
        best_pos = None
        best_score = 0.0
        for pos, vec in self._position_vectors.items():
            sim = self.vectorizer.cosine(query_vec, vec)
            if sim > best_score:
                best_score = sim
                best_pos = pos
        if best_score >= 0.6 and best_pos:
            industry, func = self.position_map[best_pos]
            logger.debug(
                f"Layer 2 match: '{best_pos}' (sim={best_score:.3f})"
            )
            return {
                "industry_tag": industry,
                "function_tag": func,
                "position_tag": best_pos,
            }
        return None

    def _layer3_llm(self, title: str, raw_text: str) -> Dict:
        """Layer 3: LLM fallback. Returns default values, marks for review."""
        logger.warning(
            f"Layer 3 LLM fallback triggered for JD: '{title}'. "
            "Requires LLM_CLIENT env var to be configured."
        )
        # Try lazy import of LLM client if configured
        try:
            import os
            if os.environ.get("LLM_CLIENT"):
                from tools.llm import LLMClient
                # Placeholder: actual LLM call would go here
                logger.info("LLM fallback available but not yet wired in classifier.")
        except Exception:
            pass

        return {
            "industry_tag": None,
            "function_tag": None,
            "position_tag": None,
        }
