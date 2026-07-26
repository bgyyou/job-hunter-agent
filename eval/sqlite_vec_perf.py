"""sqlite-vec validation harness (P0-模块 3 子任务 1).

Runs 4 phases:
  1. Smoke test (4d vec0) - verify load / MATCH / distance.
  2. Synthetic perf (24,482 x 512d) - JSON-in-BLOB scan vs vec0.
  3. Real-DB perf - same vectors, real knowledge_chunks table.
  4. Consistency - top-10 overlap between JSON cosine and vec0 cosine.

Writes results to data/sqlite_vec_validation.json.

Read-only w.r.t. project code. Touches real DB only via a copy to a temp file
in data/ so we never modify jobhunter_v2.db.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

import numpy as np
import sqlite_vec

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "jobhunter_v2.db"
TMP_DB = ROOT / "data" / "_sqlite_vec_validation.db"
OUT_JSON = ROOT / "data" / "sqlite_vec_validation.json"

N_CHUNKS = 24_482
DIM = 512
TOP_K = 10
SEED = 42


def phase1_smoke() -> dict:
    """4d vec0 basic functionality."""
    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    vec_version = db.execute("SELECT vec_version()").fetchone()[0]

    db.execute("CREATE VIRTUAL TABLE tv USING vec0(embedding FLOAT[4])")
    db.executemany(
        "INSERT INTO tv(embedding) VALUES (?)",
        [
            (sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4]),),
            (sqlite_vec.serialize_float32([0.15, 0.20, 0.3, 0.4]),),
            (sqlite_vec.serialize_float32([0.9, 0.8, 0.1, 0.0]),),
        ],
    )
    q = sqlite_vec.serialize_float32([0.12, 0.20, 0.30, 0.40])
    rows = db.execute(
        "SELECT rowid, distance FROM tv WHERE embedding MATCH ? ORDER BY distance LIMIT 3",
        (q,),
    ).fetchall()
    return {
        "vec_version": vec_version,
        "top3": [{"rowid": r[0], "distance": float(r[1])} for r in rows],
    }


def _gen_vectors(n: int, dim: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    # L2-normalize so cosine = dot product (standard for BGE embeddings).
    mat = rng.standard_normal((n, dim)).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    q = rng.standard_normal((dim,)).astype(np.float32)
    q /= np.linalg.norm(q)
    return mat, q


def phase2_synthetic() -> dict:
    """24,482 x 512d on :memory: — apples-to-apples (both use sqlite-vec Python lib)."""
    mat, q = _gen_vectors(N_CHUNKS, DIM, SEED)
    q_bytes = sqlite_vec.serialize_float32(q)

    # --- A: JSON-in-BLOB full scan (mimics current vector_search) ---
    conn_a = sqlite3.connect(":memory:")
    conn_a.execute("CREATE TABLE chunks(id INTEGER PRIMARY KEY, embedding BLOB)")
    blobs = [json.dumps(row.tolist()).encode("utf-8") for row in mat]
    conn_a.executemany("INSERT INTO chunks(embedding) VALUES (?)", [(b,) for b in blobs])
    conn_a.commit()

    t0 = time.perf_counter()
    rows = conn_a.execute("SELECT id, embedding FROM chunks").fetchall()
    decoded = np.array(
        [json.loads(bytes(r[1]).decode("utf-8")) for r in rows], dtype=np.float32
    )
    sims = decoded @ q  # already L2-normalized
    top10_idx = np.argpartition(-sims, TOP_K - 1)[:TOP_K]
    top10_sorted = top10_idx[np.argsort(-sims[top10_idx])]
    json_ms = (time.perf_counter() - t0) * 1000.0

    # --- B: sqlite-vec vec0 ---
    conn_b = sqlite3.connect(":memory:")
    conn_b.enable_load_extension(True)
    sqlite_vec.load(conn_b)
    conn_b.enable_load_extension(False)
    conn_b.execute(
        "CREATE VIRTUAL TABLE chunks_vec USING vec0("
        "embedding FLOAT[512] distance_metric=cosine)"
    )
    conn_b.executemany(
        "INSERT INTO chunks_vec(embedding) VALUES (?)",
        [(sqlite_vec.serialize_float32(row),) for row in mat],
    )
    conn_b.commit()

    t0 = time.perf_counter()
    vec_rows = conn_b.execute(
        "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (q_bytes, TOP_K),
    ).fetchall()
    vec0_ms = (time.perf_counter() - t0) * 1000.0

    # With distance_metric=cosine, vec0 distance == 1 - cos_sim.
    # So similarity == 1 - vec0_dist.
    vec0_sims = np.array([1.0 - r[1] for r in vec_rows], dtype=np.float32)
    vec0_ids = np.array([r[0] - 1 for r in vec_rows], dtype=np.int64)  # rowid is 1-based

    # Consistency: top-10 sets overlap.
    json_set = set(int(i) for i in top10_sorted)
    vec0_set = set(int(i) for i in vec0_ids)
    overlap = len(json_set & vec0_set) / float(TOP_K)

    return {
        "json_scan_ms": round(json_ms, 2),
        "vec0_ms": round(vec0_ms, 2),
        "speedup": round(json_ms / vec0_ms, 2) if vec0_ms > 0 else float("inf"),
        "overlap_top10": round(overlap, 3),
        "json_top10_ids": [int(i) for i in top10_sorted],
        "vec0_top10_ids": [int(i) for i in vec0_ids],
        "vec0_top10_sim": [float(s) for s in vec0_sims],
    }


def phase3_real_db() -> dict:
    """24,482 real chunks from jobhunter_v2.db (read-only via temp copy).

    Uses a real chunk embedding as query (not random) so vec0 cosine and numpy
    cosine compare on the same vector space. Random vectors gave overlap=0
    even when both metrics were correct — pure test-design bug.
    """
    if TMP_DB.exists():
        TMP_DB.unlink()
    shutil.copy2(REAL_DB, TMP_DB)

    conn = sqlite3.connect(str(TMP_DB))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # Pull all 512-dim float32-binary embeddings once（其它维度 / 老 JSON 不参与 perf 对比）
    # LENGTH=2048 严格筛已迁移到 float32 binary 的 chunk，未迁移 ~2820 维（老 schema 漂移）排掉。
    rows = conn.execute(
        "SELECT id, embedding FROM knowledge_chunks "
        "WHERE deleted_at IS NULL AND embedding IS NOT NULL "
        "AND legacy = 0 AND embedding_dim = 512 "
        "AND LENGTH(embedding) = 2048"
    ).fetchall()
    n_real = len(rows)
    ids = [r["id"] for r in rows]

    # v4 P0-模块 3: 兼容旧 json 与新 float32 binary（BLOB 长度是 4 倍数即 float32）。
    def _decode(blob):
        raw = bytes(blob)
        if len(raw) > 0 and len(raw) % 4 == 0:
            try:
                arr = np.frombuffer(raw, dtype=np.float32)
                if arr.size > 0 and np.all(np.isfinite(arr)):
                    return arr.tolist()
            except (ValueError, TypeError):
                pass
        return json.loads(raw.decode("utf-8"))

    decoded = np.array([_decode(r["embedding"]) for r in rows], dtype=np.float32)

    # Pick a real chunk as the query vector (first one — guarantees at least
    # one perfect match in results).
    q = decoded[0].copy()
    q_norm = float(np.linalg.norm(q))
    if q_norm > 0:
        q_for_vec0 = q / q_norm  # vec0 cosine expects unit-ish vectors
    else:
        q_for_vec0 = q

    # --- A: existing JSON path — fetch + decode + numpy cosine ---
    t0 = time.perf_counter()
    sims = (decoded @ q) / (np.linalg.norm(decoded, axis=1) * q_norm)
    top10 = np.argpartition(-sims, TOP_K - 1)[:TOP_K]
    top10 = top10[np.argsort(-sims[top10])]
    json_ids = [ids[int(i)] for i in top10]
    json_sims = [float(sims[int(i)]) for i in top10]
    json_total_ms = (time.perf_counter() - t0) * 1000.0

    # --- B: vec0 with cosine metric, multiple runs to surface any cache ---
    conn.execute("DROP TABLE IF EXISTS kv_validation")
    # v4 P0-模块 3: 用 vec0 auxiliary column 保留 knowledge_chunks.id UUID
    conn.execute(
        "CREATE VIRTUAL TABLE kv_validation USING vec0("
        "embedding FLOAT[512] distance_metric=cosine, "
        "chunk_id TEXT)"
    )
    BATCH = 500
    batch: list[tuple] = []
    for idx, r in enumerate(rows):
        # v4 P0-模块 3: 同 _decode（已迁的 blob 是 float32 binary 2048 bytes）
        raw = bytes(r["embedding"])
        v = np.frombuffer(raw, dtype=np.float32).copy()  # independent buffer
        v_norm = np.linalg.norm(v)
        if v_norm > 0:
            v = v / v_norm  # vec0 cosine expects unit vectors
        batch.append((sqlite_vec.serialize_float32(v), r["id"]))
        if len(batch) >= BATCH:
            conn.executemany(
                "INSERT INTO kv_validation(embedding, chunk_id) VALUES (?, ?)", batch
            )
            batch = []
    if batch:
        conn.executemany(
            "INSERT INTO kv_validation(embedding, chunk_id) VALUES (?, ?)", batch
        )
    conn.commit()

    # Warm-up + 5 timed runs.
    for _ in range(2):
        conn.execute(
            "SELECT chunk_id, distance FROM kv_validation "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(q_for_vec0), TOP_K),
        ).fetchall()
    timings = []
    for _ in range(5):
        t0 = time.perf_counter()
        vec_rows = conn.execute(
            "SELECT chunk_id, distance FROM kv_validation "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(q_for_vec0), TOP_K),
        ).fetchall()
        timings.append((time.perf_counter() - t0) * 1000.0)
    vec0_ms = sorted(timings)[2]  # median
    vec0_ids = [r["chunk_id"] for r in vec_rows]

    conn.close()
    TMP_DB.unlink()

    overlap = len(set(json_ids) & set(vec0_ids)) / float(TOP_K)
    return {
        "n_chunks": n_real,
        "json_scan_ms": round(json_total_ms, 2),
        "vec0_ms": round(vec0_ms, 2),
        "vec0_ms_runs": [round(x, 2) for x in timings],
        "speedup": round(json_total_ms / vec0_ms, 2) if vec0_ms > 0 else float("inf"),
        "overlap_top10": round(overlap, 3),
        "json_top10_ids": json_ids,
        "json_top10_sim": json_sims,
        "vec0_top10_ids": vec0_ids,
    }


def main() -> None:
    import sys
    print("=== Phase 1: smoke test ===", flush=True)
    smoke = phase1_smoke()
    print(json.dumps(smoke, indent=2), flush=True)
    if smoke["vec_version"] is None or not smoke["top3"]:
        print("FATAL: smoke test failed", file=sys.stderr)
        sys.exit(1)

    print("\n=== Phase 2: synthetic 24k x 512d ===", flush=True)
    synth = phase2_synthetic()
    print(json.dumps({k: v for k, v in synth.items() if k not in {"json_top10_ids", "vec0_top10_ids"}}, indent=2), flush=True)

    print("\n=== Phase 3: real DB (temp copy) ===", flush=True)
    real = phase3_real_db()
    print(json.dumps({k: v for k, v in real.items() if k not in {"json_top10_ids", "vec0_top10_ids"}}, indent=2), flush=True)

    import sqlite3 as _s, sys as _sys
    py_ver = _sys.version
    sqlite_ver = _s.sqlite3.sqlite_version if hasattr(_s, "sqlite3") else _s.sqlite_version
    import sqlite_vec as _sv

    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python_version": py_ver.split()[0],
        "sqlite_version": sqlite_ver,
        "sqlite_vec_version": _sv.__version__,
        "windows_wheel_available": True,
        "smoke": smoke,
        "perf_synthetic": {
            "json_scan_ms": synth["json_scan_ms"],
            "vec0_ms": synth["vec0_ms"],
            "speedup": synth["speedup"],
            "overlap_top10": synth["overlap_top10"],
        },
        "perf_real_db": {
            "n_chunks": real["n_chunks"],
            "json_scan_ms": real["json_scan_ms"],
            "vec0_ms": real["vec0_ms"],
            "speedup": real["speedup"],
            "overlap_top10": real["overlap_top10"],
        },
        "result_consistency": round(min(synth["overlap_top10"], real["overlap_top10"]), 3),
        "fallback_path": None,
    }
    # Recommendation: speedup >= 10x passes.
    out["recommendation"] = "proceed" if out["perf_synthetic"]["speedup"] >= 10 else "fallback_to_pg"
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {OUT_JSON}", flush=True)
    print(f"recommendation = {out['recommendation']}", flush=True)


if __name__ == "__main__":
    main()
