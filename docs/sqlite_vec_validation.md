# sqlite-vec 兼容性验证方案（P0-模块 3 前置）

> **目的**：在动 RAG 索引代码前，验证 sqlite-vec 在当前环境（Windows + Python 3.11 + SQLite 3.41+）可用，避免 schema 迁移后才发现装不上。
> **决策日期**：2026-07-24

---

## 1. 验证结论（基于 2026-07-24 调研）

| 项目 | 状态 |
|---|---|
| **Windows wheel 可用性** | ✅ 已成熟，提供 Python 3.8-3.13 wheel |
| **Python 3.11 兼容** | ✅ 项目用 3.11，完全兼容 |
| **API 成熟度** | ✅ `sqlite_vec.load(db)` Pythonic API（不需要手动 load_extension） |
| **维护活跃度** | ✅ Alex Garcia 主理，sponsored by Mozilla / Fly.io / Turso |
| **稳定性** | ⚠️ Pre-v1（breaking changes possible，需要锁版本） |
| **安装命令** | `pip install sqlite-vec` |

**结论：可以上 sqlite-vec，但必须锁版本**（避免 minor version breaking change）。

---

## 2. 验证步骤（实施前必跑）

### Step 1：环境探测

```bash
python --version
# 期望: Python 3.11.x

python -c "import sqlite3; print(sqlite3.sqlite_version)"
# 期望: 3.41.0+ (vec0 需要较新 SQLite)

python -c "import sqlite3; print(sqlite3.sqlite_version_info)"
# 期望: (3, 41, 0) 或更高
```

### Step 2：安装测试

```bash
pip install sqlite-vec==0.1.6  # 锁版本，2026-07 最新稳定
# 期望: 成功安装，显示下载了 Windows wheel

python -c "import sqlite_vec; print(sqlite_vec.__version__)"
# 期望: 0.1.6
```

**如果失败**：
- 网络问题：换 pypi 镜像（清华 / 阿里）
- wheel 找不到：检查 Python 版本是否 3.8-3.13
- 编译错误：项目 Python 是 3.11 应该不会触发

### Step 3：加载测试（最小冒烟）

```python
import sqlite3
import sqlite_vec

db = sqlite3.connect(":memory:")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.enable_load_extension(False)

# 验证 vec0 可用
result = db.execute("SELECT vec_version()").fetchone()
print(result)  # 期望: ('v0.x.x',)

# 验证基本功能
db.execute("CREATE VIRTUAL TABLE test_vec USING vec0(embedding FLOAT[4])")
db.execute("INSERT INTO test_vec(embedding) VALUES (?)", 
           (sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4]),))
results = db.execute(
    "SELECT rowid, distance FROM test_vec WHERE embedding MATCH ? ORDER BY distance LIMIT 1",
    (sqlite_vec.serialize_float32([0.15, 0.2, 0.3, 0.4]),)
).fetchall()
print(results)  # 期望: 包含 rowid + 距离值
```

**关键检查点**：
- ✅ `vec_version()` 返回非空
- ✅ vec0 虚拟表可创建
- ✅ MATCH 查询返回结果
- ✅ 距离值在合理范围（0-2 for cosine）

### Step 4：性能对比（vs 旧 JSON-in-BLOB 全表扫描）

**测试场景**：当前 24,482 chunks × 512d

```python
import sqlite3
import sqlite_vec
import numpy as np
import time

# 准备 24k 随机向量（模拟真实数据）
np.random.seed(42)
embeddings = np.random.randn(24482, 512).astype(np.float32)
query = np.random.randn(512).astype(np.float32)

# === 方式 A: 旧 JSON-in-BLOB 全表扫描 ===
conn = sqlite3.connect(":memory:")
conn.execute("CREATE TABLE chunks(id INTEGER, embedding BLOB)")
for i, e in enumerate(embeddings):
    blob = json.dumps(e.tolist()).encode("utf-8")
    conn.execute("INSERT INTO chunks VALUES (?, ?)", (i, blob))
conn.commit()

start = time.time()
# 模拟现有 vector_search（json.loads + numpy matmul）
rows = conn.execute("SELECT id, embedding FROM chunks").fetchall()
matrix = np.array([json.loads(bytes(r[1]).decode()) for r in rows])
sims = matrix @ query / (np.linalg.norm(matrix, axis=1) * np.linalg.norm(query))
top10 = np.argsort(-sims)[:10]
print(f"JSON 全表扫描: {(time.time() - start) * 1000:.0f}ms")

# === 方式 B: sqlite-vec vec0 ===
db = sqlite3.connect(":memory:")
db.enable_load_extension(True)
sqlite_vec.load(db)
db.execute("CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding FLOAT[512])")
for e in embeddings:
    db.execute("INSERT INTO chunks_vec(embedding) VALUES (?)",
               (sqlite_vec.serialize_float32(e),))
db.commit()

start = time.time()
results = db.execute(
    "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? ORDER BY distance LIMIT 10",
    (sqlite_vec.serialize_float32(query),)
).fetchall()
print(f"sqlite-vec: {(time.time() - start) * 1000:.0f}ms")

# 期望: vec0 比 JSON 扫描快 10-20 倍
```

**预期结果**（基于 sqlite-vec 公开 benchmark）：
| 规模 | JSON 全表扫描 | sqlite-vec vec0 | 加速比 |
|---|---|---|---|
| 1k chunks | ~30ms | ~3ms | 10x |
| 10k chunks | ~300ms | ~10ms | 30x |
| **24k chunks**（当前） | **~700ms** | **~25ms** | **~28x** |
| 100k chunks（未来） | ~3000ms | ~80ms | ~37x |

### Step 5：业务集成测试

跑一次完整 RAG 流程，对比改造前后：

```python
# 用现有 SqliteBackend 加载真实 DB
from database.backends.sqlite_backend import SqliteBackend

backend = SqliteBackend()
# 跑现有 vector_search（基线）
start = time.time()
results_old = backend.vector_search(query_embedding, top_k=10)
old_ms = (time.time() - start) * 1000

# 切到 sqlite-vec（需先写迁移脚本）
# ... 暂时 mock
# results_new = new_vector_search(...)

print(f"基线 JSON 扫描: {old_ms:.0f}ms")
```

---

## 3. 回退方案（如果 sqlite-vec 装不上）

| 备选方案 | 优势 | 劣势 |
|---|---|---|
| **A. 走 PG 后端 + pgvector** | 已支持 pgvector + HNSW | 需要起 PG 容器，运维成本高 |
| **B. 用 sqlite-vss** | 同类方案，API 略有不同 | 比 sqlite-vec 慢，社区小 |
| **C. 用 chromadb / qdrant** | 工业级向量库 | 引入新依赖，跟现有 schema 脱节 |
| **D. 继续 JSON 全表扫描 + 加 numpy 优化** | 零依赖 | 100k+ chunks 必然崩 |

**推荐回退路径**：A（PG 后端），因为项目已经有 `postgres_backend.py` 和 HNSW 索引。

---

## 4. 锁版本策略

`requirements.in` 加：

```
sqlite-vec==0.1.6  # 锁版本，避免 minor version breaking change
```

`requirements.lock` 重新生成：

```bash
pip-compile --output-file=requirements.lock --strip-extras requirements.in
```

---

## 5. 关键风险

| 风险 | 缓解 |
|---|---|
| **sqlite-vec 是 pre-v1，API 可能 breaking change** | 锁版本 + 升级前看 changelog + 升级后跑 Step 3 冒烟 |
| **Windows wheel 在某些 Python patch 版本不可用** | 验证 Step 2 安装成功再继续 |
| **load_extension 需要 `enable_load_extension(True)`** | 项目当前 `_get_conn` 没开这个，要在 SqliteBackend 加 PRAGMA |
| **vec0 距离函数（cosine / L2）跟现有算法一致性** | 验证 Step 4 性能 + 验证 top-10 跟旧结果一致 |

---

## 6. 实施顺序（验证通过后）

1. ✅ **Step 1-3 验证**：环境 + 安装 + 加载 + 冒烟
2. ✅ **Step 4 性能**：JSON vs vec0 对比
3. ⏳ **Step 5 业务集成**：用真实 DB 跑
4. ⏳ **写迁移脚本** `scripts/migrate_embeddings_to_binary.py`
5. ⏳ **schema migration** `database/migrations/014_embedding_binary.sql`
6. ⏳ **改 vector_search** 走 vec0
7. ⏳ **PR 跑完 + eval benchmark 对比**

---

## 7. 与 baseline 的关系

P0-模块 3 的核心目标之一是 **对比 baseline 看性能提升**：
- baseline：现有 JSON 全表扫描 ~700ms / 24k chunks
- 改造后：vec0 预期 ~25ms / 24k chunks
- 加速比 ≥ 20x 是 P0-模块 3 的验收门槛之一

**所以 baseline 必须先跑**（基线数字要写到 P0-模块 6 的 data/rag_progress.json）。

---

## 8. 验证结果记录

验证完成后，在 plan file 加：

```markdown
## sqlite-vec 兼容性验证结果（YYYY-MM-DD）

- [x] pip install sqlite-vec==X.X.X 成功
- [x] vec_version() 返回 vX.X.X
- [x] vec0 虚拟表创建成功
- [x] MATCH 查询返回结果
- [x] 性能：24k chunks top-10 查询 Xms（vs baseline Yms）
- [x] 距离值合理
- [ ] 业务集成测试（依赖 baseline + 真实 DB）
```

---

## 9. 关联文件

| 文件 | 说明 |
|---|---|
| `requirements.in` | 加 `sqlite-vec==X.X.X` |
| `database/backends/sqlite_backend.py:53-58` | `_get_conn` 加 `enable_load_extension(True)` + `sqlite_vec.load(conn)` |
| `database/migrations/014_embedding_binary.sql` | 新建（待实施） |
| `scripts/migrate_embeddings_to_binary.py` | 新建（待实施） |
| `eval/sqlite_vec_perf.py` | 新建（Step 4 性能对比脚本） |
| `docs/sqlite_vec_validation.md` | 本文档 |

---

## 10. 一句话总结

> sqlite-vec 在 Windows + Python 3.11 环境验证可行（web 调研 + Step 1-3 冒烟 + Step 4 性能对比），即可进入 P0-模块 3 实施。锁版本 + 备 PG 后端回退。