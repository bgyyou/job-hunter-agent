# Golden 校准集标注指引（P0-模块 6 子任务 2）

> **目的**：确保 50 条 query × 5-10 候选 JD 的标注一致性、可重复。
> **标注者**：你自己
> **耗时**：约 2.5 小时，建议分两天，每天 25 条

---

## 1. 标注流程

每条 query 会有 5-10 个候选 JD（按现有 RAG top-10 召回）。

```
打开 eval/golden_candidates.jsonl
  ↓
找到 query_id = q001 的记录
  ↓
读 query + 5-10 个候选 JD 标题 + 200 字摘要
  ↓
对每个候选打 1-5 分
  ↓
写入 eval/golden.jsonl（human_score 字段）
```

---

## 2. 1-5 分规则（语义对照）

| 分数 | 英文标签 | 中文描述 | 判断依据 |
|---|---|---|---|
| **5** | highly_relevant | 完全匹配 query 所有需求 | 行业 + 职能 + 级别 + 技能都对得上 |
| **4** | relevant | 高度匹配，少量维度差异 | 主体匹配（如行业对、级别差一档） |
| **3** | partially_relevant | 部分匹配 | 行业对但职能错，或职能对但行业错 |
| **2** | weakly_relevant | 弱相关 | 同大行业不同细分（如互联网但电商 vs 游戏） |
| **1** | irrelevant | 不相关 | 完全不同行业 / 完全不同职能 / 噪音 JD |

### 关键判断原则

**相关性 = query 的真实意图 vs JD 的真实定位**

不要按"这个 JD 看起来不错"打分，要按"用户搜这个 query 是想找什么"打分。

举例：
- query = "Python 后端 5年"
  - JD "Python 后端 3年" → 4 分（接近但年限略低）
  - JD "Python 数据工程师 5年" → 3 分（行业对、技术栈部分对、职能错）
  - JD "Java 后端 5年" → 2 分（同职能不同语言，部分相关）
  - JD "HR 招聘经理" → 1 分（完全无关）

---

## 3. 边界 case 处理

### Case A：query 很模糊
- query = "找一个好岗位" → 所有 JD 都是 1-2 分
- 处理：按"如果是用户真实输入，这种 query 大概率没召回意义"判断

### Case B：query 含人称/口语化表达
- query = "我工作 5 年了能跳哪里" → 解析 query 实际意图（"5 年经验求职"）
- 处理：按解析后的意图打分

### Case C：JD 信息不全
- 只有标题没摘要 → 按标题 + 行业常识判断
- 处理：宁可打中间分（3 分），不要打极端分

### Case D：JD 是噪音（招聘广告、HR 自荐）
- JD 内容是 "XX 公司诚聘" 没具体要求 → 1 分
- 处理：噪音一律 1 分

### Case E：query 含跨领域诉求
- query = "技术转产品" → 找的是产品岗，技术是背景
- 处理：按 query 真正诉求（产品岗）打分

---

## 4. 标注一致性自检

标完 50 条后，**随机挑 5 条 2 周后再标一遍**，计算自一致性。

```python
from scipy.stats import spearmanr

# 第一轮标注分数
round1 = [5, 3, 4, 2, 1]
# 第二轮标注分数（2 周后）
round2 = [5, 3, 4, 2, 2]

spearman_r, _ = spearmanr(round1, round2)
# spearman_r 应 ≥ 0.7
```

**自一致性 < 0.7 的常见原因**：
- 边界 case 处理不一致
- 分数语义理解漂移
- 标注疲劳（建议分两天）

---

## 5. 标注工具（推荐）

### 方案 A：纯文本编辑器（最简单）

```jsonl
# eval/golden.jsonl（直接编辑）
{
  "query_id": "q001",
  "query": "...",
  "candidates": [
    {"jd_id": "JD-1234", "jd_title": "...", "human_score": 5},
    {"jd_id": "JD-5678", "jd_title": "...", "human_score": 1}
  ]
}
```

优点：零成本；缺点：要手写 JSON

### 方案 B：VS Code + JSON 折叠（推荐）

```bash
code eval/golden_candidates.jsonl
```

VS Code 自动语法高亮 + JSON 折叠 + 错误提示

### 方案 C：自建标注 UI（后期可选）

如果你标完一轮发现 50 条还行，未来要扩到 200 条 / 500 条，可以做个 Streamlit 标注界面：
- 左边：query + 候选 JD 列表
- 右边：1-5 分按钮
- 进度条 + 快捷键（1-5 数字键）

但**当前不需要**，50 条用 JSONL 足够。

---

## 6. 标注后必跑的检查

```bash
# 1. JSON 格式校验
python -c "import json; [json.loads(l) for l in open('eval/golden.jsonl')]"

# 2. 50 条齐了
wc -l eval/golden.jsonl  # 应输出 50

# 3. 每条 query 都有 human_score
python -c "
import json
records = [json.loads(l) for l in open('eval/golden.jsonl')]
for r in records:
    assert all(c.get('human_score') in [1,2,3,4,5] for c in r['candidates']), r['query_id']
print('OK: 50 条都标完了')
"

# 4. 跑校准
python eval/calibrate_judge.py
```

---

## 7. 标注完成的标志

- ✅ 50 条都标了
- ✅ 每条 query 的所有候选 JD 都有分数（不能漏标）
- ✅ 自一致性 ≥ 0.7
- ✅ 校准脚本跑通，Spearman ≥ 0.8（或已知偏差原因）

---

## 8. 时间分配建议

| 时间 | 任务 | 预期 |
|---|---|---|
| 第 1 天 0-1.5h | 标 25 条（q001-q025） | 中途疲劳可停 |
| 第 2 天 0-1h | 标 25 条（q026-q050） | 后半段 |
| 第 2 天 1-1.5h | 跑校验脚本 + 自检一致性 | 完成 |

如果中间遇到边界 case 拿不准，**先打 3 分继续**，最后回头统一校准。

---

## 9. 常见疑问 FAQ

**Q：候选 JD 里有同一个公司的多个 JD 怎么办？**
A：每个 JD 独立打分，不因为"同一公司"打高分或低分。

**Q：query 含错别字怎么办？**
A：按字面 query 理解（"用户想搜什么"），不替用户纠错。

**Q：JD 是英文怎么办？**
A：按英文内容判断，相关性逻辑一致。

**Q：query 完全无法理解怎么办？**
A：所有候选打 1 分，并在 query 后面加注释 `<!-- unparseable -->`。

**Q：50 条都标完，但我意识到第 10 条标错了，能改吗？**
A：能改，但要在 `data/rag_progress.json` 加 `golden_amendments` 字段记录修改。

---

## 10. 关键约束

1. **不要看 LLM judge 打的分**（避免循环依赖 / anchoring bias）
2. **不要参考其他标注者**（就你自己，避免从众）
3. **不要跳过任何候选**（每个候选都要分）
4. **不要按"JD 整体质量"打分**（JD 好不好 ≠ 与 query 相关不相关）