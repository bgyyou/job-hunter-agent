# MRR 反向跌 6.9% 根因诊断 + 修复方案 (2026-07-28)

> **TL;DR**:
> - 翻译 backfill 后 MRR 跌 6.9% 不是单一根因，**两个独立因素**各占一部分：
>   - **A. mock fallback 拉低 42%**（-0.0134 绝对值，3.0% 相对）
>   - **B. 翻译 backfill 引起 cross-source top-1 错位 58%**（-0.0182 绝对值，4.0% 相对；含 judge model 变更 noise）
> - **优先修复 B**（影响更大、影响所有 50 query），**A 作为连带优化**（跟着 #10 任务一起做 mock fallback 治理）。
> - 修复 B 之后，预期 MRR 从 0.4419 涨到 0.50+。

---

## 1. 数据基础

| Run | ts | judge model | mock | NDCG | Recall | MRR | Hit | n_zero |
|---|---|---|---|---|---|---|---|---|
| T4 rerank ON 前 backfill | 2026-07-25T11:09:55Z | agnes-2.0-flash | 8/50 | 0.5379 | 0.3620 | **0.4601** | 0.7000 | 15 |
| T5 backfill 后 | 2026-07-26T08:03:43Z | MiniMax-M3 | 6/50 | 0.6033 | 0.4880 | **0.4285** | 0.9000 | 5 |
| **T6 本次复现** | 2026-07-28T08:15:51Z | MiniMax-M3 | 0/50 | 0.6460 | 0.5380 | **0.4419** | 0.9600 | 2 |

- T5→T6 = **ΔMRR +0.0134** (mock 减少 8→0)
- T4→T6 = **ΔMRR -0.0182** (翻译 backfill + judge model 变化)
- T4→T5 = **ΔMRR -0.0316 = -6.9%** (官方记录的"反向跌")

复现数据：50 query 完整 per-candidate 详情落盘
- `data/diag_full_20260728T082712Z.jsonl` (50 行 × 11 字段 / candidate)
- `data/diag_candidates_20260728T082216Z.jsonl` (50 query 完整 top-10 candidates)
- `data/eval_baseline_20260728T081551Z.json` (原始 baseline json)

---

## 2. 根因 A：mock fallback（42%）

### 现象
T5 (mock=6) 跟 T6 (mock=0) 唯一变量是 mock fallback query 数。模拟 100 次随机 6-mock 子集得到：

```
T6 真实 (mock=0):            MRR = 0.4419
T5 模拟 6-mock 中位 (100次): MRR = 0.4245  (95% 区间 [0.3654, 0.4665])
T5 实测 (mock=6, MiniMax):   MRR = 0.4285  ← 落在模拟区间内 ✓
```

**实测 mock 影响**：T5 - T6 = **-0.0134 绝对值 (-3.0% 相对)** = 占 6.9% 总跌的 **42%**。

### 机理
`eval/judge.py:_mock_judge` 对无词重叠的 (query, candidate) 给 score=2，对有重叠给 score=3-4。
- 当 LLM API 因 429 限流失败，**该 query 的所有 10 个 candidate 全部 fallback 到 mock**
- mock 给分仅基于词重叠，**对 cross-lang candidate 普遍给 2-3**（"Accountant" 中文 query 跟英文 JD 重叠 = 0 → 全 2）
- 6 条 mock query 的真实 judge 信号被噪声替代，**直接拉低该 query 的 NDCG/Recall/MRR**

### 验证
- 100 次随机 6-mock 子集 → 中位 MRR 0.4245，95% 区间覆盖 0.4285 → 假设成立
- 6 mock query 的 mock scores 范围 [2,2,2,2,2,2,2,2,2,3] ~ [4,4,4,4,4,4,4,4,2,2]，top-1 多数 2-4（无 LLM 的精细打分）

### 修复（不在本次范围，跟 #10 任务做）
- ✅ **重试 + 退避增强**（已部分实现）
- ⏳ **mock fallback 隔离**（mock 给分标记但 score 重置为 None，不计入 metrics）
- ⏳ **LLM judge 429 限流降到 <3%**（#10 任务）
- ⏳ **LLM 缓存复用**（跨 run 复用 batch_per_query 响应，已部分实现）

---

## 3. 根因 B：翻译 backfill 引起 cross-source top-1 错位（58%）

### 现象
本次复现 T6 的 retrieval 阶段（不依赖 LLM judge）：

| 指标 | 数值 | 解读 |
|---|---|---|
| top-1 == origin_jd | **2/50 = 4%** | 极低：retrieval 自己把 origin 排不到第一 |
| top-3 has origin_jd | 3/50 = 6% | 同上 |
| top-10 has origin_jd | 8/50 = 16% | 多数 query origin 干脆不在 top-10 |
| **top-1 100% 都是 jobsdb_batch** | 50/50 | 跨 lang 召回英文 JD |
| top-1 cross-source | 28/50 = **56%** | origin 是 51job/liepin 时 top-1 全是 jobsdb |
| top-1 cross-source & score=1 | **21/50 = 42%** | "错位噪声" |
| top-1 cross-source & score≥3 | 6/50 = 12% | 真相关（中文 query 命中英文同 title JD） |

按 origin_source 拆开看：

| source | n | NDCG | Recall | MRR | Hit | top-1 是 origin |
|---|---|---|---|---|---|---|
| 51job_batch (中文) | 20 | 0.6089 | 0.4900 | 0.4085 | 0.95 | 0/20 |
| jobsdb_batch (英文) | 17 | 0.6541 | 0.5529 | 0.4255 | 0.94 | 2/17 |
| liepin_batch (中文) | 8 | 0.6526 | 0.5250 | 0.4677 | 1.00 | 0/8 |
| cross_domain (无 origin) | 5 | 0.7565 | 0.7000 | 0.5900 | 1.00 | n/a |

→ **中文 query (28 条) top-1 100% 都是 cross-source (jobsdb 英文)**。
→ 但中文 query MRR (0.4254) ≈ 英文 query MRR (0.4255)，**翻译 backfill 让跨语言检索性能对等**。

### 量化
T4 (前 backfill, agnes) MRR=0.4601 → T6 (backfill 后, MiniMax) MRR=0.4419
**ΔMRR = -0.0182 绝对值 (-4.0% 相对) = 占 6.9% 总跌的 58%**

> ⚠️ 这部分包含 judge model 变更的 noise（agnes→MiniMax）。要严格归因需要用同一 judge 重跑翻译前 retrieval（成本 ~3.5 min × 1 次，cache 命中 0 token，作为 P1-模块 1 验证任务）。

### 机理
翻译 backfill 之前：英文 query 走英文向量，中文 query 走中文向量，**跨语言候选根本进不了 rerank 池**。
翻译 backfill 之后：所有英文 chunk 翻译成中文入库，**中文 query 现在能匹配到英文 JD 的中文翻译 chunk**，rerank 把它抬到 top-1。

具体 case（top-1 错位噪声 21 条）：

| qid | origin_source | top-1 (cross-source) | judge | 期望（同源 origin 在） |
|---|---|---|---|---|
| q0038 | 51job | jobsdb: "Education Consultant/ Senior Education Consultant" | 1 | origin 51job: "课程顾问..." |
| q0084 | 51job | jobsdb: "Account Manager – Enterprise Solution" | 1 | origin 51job: "集团招聘经理（coe）" |
| q0162 | 51job | jobsdb: "Product Manager" | 1 | origin 51job: "产品助理（底薪8K起）" |
| q0028 | 51job | jobsdb: "Product Designer (Home Décor / Seasonal Products)" | 1 | origin 51job: "电商平面设计师" |
| q0175 | 51job | jobsdb: "Accountant" | 1 | origin 51job: "税务会计" |
| q0096 | 51job | jobsdb: "Shipping Officer" | 1 | origin 51job: "外贸业务员（俄语）" |
| q0110 | 51job | jobsdb: "UI/UX Designer (IT Solutions)" | 1 | origin 51job: "体系工程师" |
| q0027 | 51job | jobsdb: "HK Marketing and Enrollment Manager" | 1 | origin 51job: "海外销售" |
| q0017 | 51job | jobsdb: "Senior Manager - Investment Feasibility" | 1 | origin 51job: "高级体系系统工程师" |
| q0072 | 51job | jobsdb: "Marketing Officer" | 1 | origin 51job: "地推运营" |

→ 这些都是**中文 query 召回的英文 JD title 跟 query 词面相关**（"Accountant" query 命中英文 "Accountant" JD），
→ **但实际 JD 内容 / industry / 职责不匹配**（中文 "税务会计" 跟英文 "Accountant" 不一样），
→ 翻译 backfill 让这种"title 表面相关"被 rerank 抬到 top-1，**真实相关的中文 origin 反而在后**。

### 修复（推荐方案）

#### B-1. 跨语言信号软加权（**P1-模块 1 优先**）

**改动**：`services/retrieval_service.py` 的 `_industry_weight` 增强，新增 `cross_lang_weight`：

```python
# 当前 (services/retrieval_service.py:117):
ind_w = self._industry_weight(row.get("jd_industry_tag"), boost_industry)

# 改：把"cross-lang 候选"软降权
def _cross_lang_weight(cand_source: Optional[str], origin_source: Optional[str]) -> float:
    """跨语言候选软降权（不 hard filter，让 true cross-lang relevant 仍能浮上来）。"""
    if not cand_source or not origin_source:
        return 1.0
    if cand_source == origin_source:
        return 1.0
    # cross-lang 候选 soft downweight，但保证 true relevant 仍能进 top-3
    return 0.85

# 在 ranked 公式里乘进去:
ranked = 0.7 * rr_norm + 0.3 * sim * type_w * ind_w * cross_lang_w
```

**预期影响**：
- 中文 query 召回的英文 top-1 (score=1 噪声) → 降权 → top-1 回归中文 origin
- 6 条 cross-lang 真相关 (score≥3) → 因 cross_lang_w=0.85 + 真 rerank_score 高 → 仍能进 top-3
- 预期 MRR 涨 0.05-0.10（21 条 top-1 错位 query 各贡献 1/1 - 1/rank 提升）
- NDCG/Recall 略降（少 1-2 个 relevant 在 top-10），但**以 NDCG-2% 换 MRR +10%+ 值得**

**风险**：0.85 是猜的，建议 A/B（0.7 / 0.85 / 0.9）。

#### B-2. 跨语言候选 `min_similarity` 硬阈值（**P1-模块 1 备选**）

```python
# 对 cross-source candidate, min_similarity 从 0.0 提到 0.55
if cand_source != origin_source and sim < 0.55:
    continue
```

**问题**：硬阈值，recall 会跌（同 title 英文 JD 即使内容相关也 0.55 以下会被砍）。
**建议**：先用 B-1 软降权，B-2 作为 P1-模块 1 后期调优。

#### B-3. reranker 加 industry/position 对齐信号（**P1-模块 4**）

**改动**：`tools/reranker.py` 的 cross-encoder prompt 加入"expected industry / position"信号：

```
# 当前 (tools/reranker.py):
# query: "中文 query"
# candidate: "英文 chunk 翻译成中文"

# 改：附带 query 的 origin_source
# rerank prompt: "query 是 51job 中文 JD，请判断 candidate 是否同职位 / 同行业 / 同职责"
```

**风险**：reranker 训练时没见过 industry 对齐信号，prompt engineering 效果不确定。建议先在 eval golden set 30 条上做离线对比。

#### B-4. query 改写（**P1-模块 1 后置**）

**思路**：中文 query 检索时**先翻译成英文**，跟英文 chunk 走同语言匹配；最后把英文 top-K 翻译回中文给用户看。

**问题**：
- 多一次 LLM 调用，cost ↑
- 翻译噪声叠加
- 不是 retrieval 阶段的事，是 query 理解阶段

**建议**：作为 P1-模块 1 后期探索，不在本次诊断范围。

---

## 4. 修复优先级（**前 3 项**）

| 序 | 任务 | 范围 | 预期 MRR 涨 | 成本 | 风险 |
|---|---|---|---|---|---|
| **#1** | **B-1 跨语言信号软降权（0.7/0.85/0.9 三组 A/B）** | `services/retrieval_service.py` (1 函数, 3 行) | **+0.05 ~ +0.10** | 1 小时（含 50q eval 复现） | 低（软降权，true relevant 仍能进 top-3） |
| **#2** | A. mock fallback 隔离（#10 任务） | `eval/judge.py` (5-10 行) | +0.0134 | 0.5 小时 | 极低 |
| **#3** | B-3 reranker industry/position 对齐 prompt | `tools/reranker.py` (1 prompt 改) | +0.02 ~ +0.05 | 2-3 小时 | 中（rerank 行为可能不稳定） |

**建议执行顺序**：B-1 → A-isolation → B-3，每步用本次 50 query 评测 + golden 30 query 评测验证。

---

## 5. 后续验证任务

| 任务 | 描述 | 成本 | 阻塞 |
|---|---|---|---|
| **#11 严格归因** | 用 T6 MiniMax judge 重跑 backfill 前 retrieval（git stash 当前翻译 + 切回 20260725T110955Z 代码），对比 ΔMRR 是否就 ≈ -0.0182 | ~3.5 min × 1 次（cache 命中 0 token） | 阻塞 B-1 量化 |
| **#12 golden 30 query 评测** | 30 条人工标 relevance 跑 50q 同 retrieval 配置 | 4-5 min × 3（A/B） | 阻塞 B-1 上线 |
| **#13 origin_jd 召回率专项** | 当前 top-10 only 16% 有 origin，定位是 rerank over-fetch 不够还是 similarity 阈值 | 0.5 小时分析 | 阻塞 B-2 |

---

## 6. 本次不修的项（标 TODO）

- [ ] **B-2 cross-lang min_similarity 硬阈值**：等 B-1 A/B 完再决定
- [ ] **B-4 query 改写**：P1-模块 1 后期
- [ ] **A. mock fallback rate 降到 <3%**（#10 任务范围）
- [ ] **judge model 切换的 noise 量化**（#11）
- [ ] **origin_jd top-10 召回率专项**（#13，retrieval 阶段问题，跟 cross-lang 独立）

---

## 7. 一句话结论

> 翻译 backfill 让**跨语言检索性能对等**（中文 query MRR ≈ 英文 query MRR），但 **56% 的 top-1 是 cross-source 错位**（其中 75% 是 score=1 噪声），**这是 MRR 跌的主因 (58%)**；mock fallback 贡献 42%。**优先做 B-1 跨语言软降权**，预期 MRR 涨 0.05+。
