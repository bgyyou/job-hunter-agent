# Golden 校准集设计规范（P0-模块 6 子任务 2）

> **目的**：为 LLM-as-judge 提供"标准答案"，监控 LLM judge 的判分质量。
> **决策日期**：2026-07-24
> **样本量**：50 条 query × 5-10 候选 JD
> **标注者**：项目维护者（你自己）
> **标注维度**：1-5 分连续相关性

---

## 1. 数据结构（eval/golden.jsonl）

```jsonl
{
  "query_id": "q001",
  "query": "Python 后端 5年经验 跨境电商",
  "query_source": "51job",
  "query_length_bucket": "medium",
  "industry_hint": "互联网/电商",
  "candidates": [
    {
      "jd_id": "JD-1234",
      "jd_title": "高级 Python 后端工程师",
      "jd_snippet": "5年 Python 经验，跨境电商业务背景优先，...",
      "human_score": 5,
      "human_relevance_label": "highly_relevant"
    }
  ]
}
```

**字段说明**：
- `query_id`：自增编号 `q001`-`q050`
- `query`：原始用户查询
- `query_source`：JD 来源（51job / jobsdb / liepin / boss）
- `query_length_bucket`：short (1-5词) / medium (6-15词) / long (>15词)
- `industry_hint`：粗行业分类（互联网 / 金融 / 制造 / ...）
- `candidates`：5-10 个候选 JD，每个含：
  - `jd_id`：候选 JD 编号
  - `jd_title`：JD 标题
  - `jd_snippet`：JD 前 200 字摘要
  - `human_score`：人工标注 1-5 分
  - `human_relevance_label`：human_score 对应的语义标签

---

## 2. 标注维度（1-5 分）

| 分数 | 语义 | 描述 |
|---|---|---|
| **5** | highly_relevant | 完全匹配 query 需求 |
| **4** | relevant | 高度匹配，少量维度差异 |
| **3** | partially_relevant | 部分匹配（如行业对、级别错） |
| **2** | weakly_relevant | 弱相关（同行业不同职能） |
| **1** | irrelevant | 不相关 |

---

## 3. 抽样策略（分层 + 难度）

### 分层维度（保证覆盖）

| 维度 | 分布 |
|---|---|
| **来源** | 51job 17 / jobsdb 17 / liepin 8 / boss 8（≈总 JD 分布） |
| **query 长度** | short 17 / medium 17 / long 16 |
| **行业** | 互联网 25 / 金融 10 / 制造 8 / 其他 7 |

### 难度维度（基于 baseline NDCG）

baseline 跑完后按 query NDCG 分桶：
- **Easy**（NDCG ≥ 0.8）：20 条，LLM judge 应该都对
- **Hard**（NDCG ≤ 0.3）：15 条，召回失败的 case
- **Boundary**（人工挑 NDCG 0.4-0.7 且 score 3-4 居多的）：15 条，最容易判错

**抽样脚本位置**：`eval/sample_golden.py`

---

## 4. 校准指标（必跑）

```python
from scipy.stats import spearmanr, pearsonr

# golden_scores：人工 1-5 分
# llm_scores：LLM judge 1-5 分
spearman_r, _ = spearmanr(golden_scores, llm_scores)
pearson_r, _ = pearsonr(golden_scores, llm_scores)
```

**门槛**：
- Spearman ≥ 0.8 → LLM judge 可信，可替代人工做日常评测
- Spearman 0.6-0.8 → 黄金地带，调 prompt / 换 judge 模型
- Spearman < 0.6 → LLM judge 不可信，必须人工评测

---

## 5. 实施步骤

1. ✅ **子任务 1 跑 baseline**：LLM judge 已有分数
2. ✅ **抽样脚本生成候选**：`python eval/dump_golden_candidates.py` 输出 `eval/golden_candidates.jsonl`（50 条候选）
3. ✅ **抽 30 条 golden 骨架**：`python scripts/extract_golden_30.py` → `eval/golden_30_to_annotate.jsonl`
4. ✅ **PRELIMINARY 标签占位**：`python scripts/build_golden_30_preliminary.py` → `eval/golden_30_preliminary.jsonl`
   - **PRELIMINARY 标签**：LLM judge score≥3 二值化为 1，是占位标，**不是真 golden**，待人工按 `annotation_guide.md` 覆盖
5. ⏳ **人工标注**：按 `eval/annotation_guide.md` 给 `golden_30_to_annotate.jsonl` 每个候选打 1-5 分
6. ✅ **Spearman 验证**：`python scripts/verify_golden_spearman.py` → ρ + 报告
   - 校验 LLM judge NDCG@10 vs PRELIMINARY NDCG@10 的一致性；ρ ≥ 0.8 健康门槛
7. ⏳ **CI 接入**：相关系数 < 0.8 fail

---

## 6. 标注效率估算

- 50 条 × 平均 6 候选 × 30 秒/候选 = **150 分钟** ≈ 2.5 小时
- 建议分 2 次：25 条/天 × 2 天，避免疲劳

---

## 7. 一致性自检

标完后随机挑 5 条 2 周后再标一遍：
- 自一致性 ≥ 0.7：标注稳定
- < 0.7：标注指引不清，需调整

---

## 8. 文件清单（实施后）

- `eval/README.md`（本文档）
- `eval/queries.jsonl`（baseline 200+ query）
- `eval/golden_candidates.jsonl`（抽样候选，待标；50 条）
- `eval/golden_30_to_annotate.jsonl`（30 条骨架，待人工标 1-5 分）
- `eval/golden_30_preliminary.jsonl`（30 条 PRELIMINARY 二值标签，占位标）
- `eval/golden.jsonl`（最终带分数）
- `eval/judge.py`（LLM-as-judge）
- `eval/dump_golden_candidates.py`（50 条候选抽样）
- `eval/sample_golden.py`（旧抽样脚本，保留）
- `scripts/extract_golden_30.py`（30 条骨架抽取）
- `scripts/build_golden_30_preliminary.py`（PRELIMINARY 标签生成）
- `scripts/verify_golden_spearman.py`（Spearman 验证）
- `tests/unit/test_verify_golden_spearman.py`（Spearman 单测）
- `eval/annotation_guide.md`（标注指引）

---

## 9. 与 baseline 的关系

baseline 跑完后：
1. 把 baseline 结果（query NDCG）输入 `eval/sample_golden.py`
2. 抽样脚本按"分层 + 难度"挑 50 条
3. 输出 `eval/golden_candidates.jsonl`
4. 你开始标

**没有 baseline 跑不了 golden 抽样**——这就是为什么子任务 1（baseline）必须先做。