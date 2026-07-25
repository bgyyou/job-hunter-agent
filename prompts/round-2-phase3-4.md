# Round-2: v3 Phase 3 + Phase 4 实施

## 上下文

- 工作区：`C:\Users\19802\Desktop\ClaudeCodeTest\job-hunter-agent`
- 唯一权威方案：`update_plan.md`（v3 重建方案，已按本轮决策修订过）
- 项目协作规则：`CLAUDE.md`（含 commit 规范、推的时机、禁区等）
- 历史账本：`CHANGELOG.md`
- round-1 已完成（12 commit 在本地，baseline 242 → 307，新增 65 条测试），未 push 远端（GitHub 账号邮箱问题，本轮不处理）

## 本轮范围（按 update_plan.md §4.2）

```
Phase 3：文档生成
  ├─ Word 生成（python-docx + jinja2，2-3 套模板）
  └─ PDF 生成（前端方案，html2pdf 或 streamlit 内置 PDF 打印）

Phase 4：UI 改造（web_app.py render_flow_a 内部 5 个 Step）
  ├─ Step 1：行业×职能×岗位（已存在，保留） + 新增"JD 三选一入口"（text/image/rag 三个按钮）
  ├─ Step 2：渐进式披露表单（基本 / 教育 / 工作 / 项目 / 技能，每段 + 号扩展）
  ├─ Step 3：模式 A/B/auto 切换（调 services.resume_rewriter）
  ├─ Step 4：实时一页纸预览（调 services.one_page_estimator）+ 瘦身向导
  └─ Step 5：Word/PDF 导出（调 services.document_generator）+ 文件命名 `{姓名}_{岗位}_{公司}.{ext}`
```

## 关键决策（已经拍板，本轮不再讨论）

1. **改造 flow_a 内部，不新建平行入口**：`render_flow_a()` 函数升级，app_route="flow_a" 不动
2. **services/ 扁平 *.py**：不开子目录。新增 `document_generator.py` 一个文件 + `document_generator_templates/word/*.j2`（jinja2 模板按目录是惯例）
3. **PDF 用前端方案**：streamlit 的 PDF 打印 / html2pdf，不引 weasyprint
4. **Word 模板 2-3 套**：保守 / 现代 / 创意（保守 + 现代起步，创意可选 round-3）
5. **模式 B 虚线框 + [AI 模板生成] 标记**：前端用 CSS class 实现
6. **页面 schema_version 11 → 12 已完成**（round-1 提交了 011/012 迁移）
7. **schema 用 jds.parsed_sections JSON 列升级，不新建独立表**（jds 表已有，复用）
8. **直接动手不嘴问**（按 update_plan §4.4.5）

## 必读文件（先看，再动手）

按顺序：
1. `update_plan.md` — 通读，特别是 §1（产品决策）、§2（技术方案）、§4.2（实施节奏）、§6（验收标准）
2. `CLAUDE.md` §3 — commit 规范、推的时机、禁区
3. `CHANGELOG.md` 末尾 — round-1 记录（理解已经做了什么）
4. `web_app.py` 的 `render_flow_a()` 函数（1119-1500 行）— 理解现有流程
5. `services/resume_rewriter.py` — round-1 实现的改写服务（Step 3 调它）
6. `services/jd_parser.py` — round-1 实现的 JD 解析器（Step 1 的"text" 路径调它）
7. `services/one_page_estimator.py` — round-1 实现的预估器（Step 4 调它）
8. `services/information_scorer.py` — round-1 实现的评分器（Step 3 auto 模式调它）

## 实施建议（不是硬要求，但建议这样拆）

### Step 0: 先做"渐进迁移 vs 整体重写"的判断

`render_flow_a()` 当前 380 行，5 个 Step 的所有逻辑 + 状态机 + session_state 管理全塞里面。
**风险**：整段重写风险高、易破坏 v2.1 flow-a 已稳定运行的部分。

**建议路径**（写进 update_plan §4.2 Phase 4 即可，不重新讨论）：

```
方案 A：渐进迁移
  - 保留 render_flow_a() 框架 + session_state 字段
  - 逐 Step 替换内部实现（5 个 Step = 5 个 sub-commit）
  - 每 Step 替换后跑 pytest tests/ -q 确认不破

方案 B：整体重写
  - 拆 render_flow_a() 为 5 个子函数 render_flow_a_step_N()
  - 一次性写完所有 5 个 Step
  - 风险高，回归测试成本大
```

**推荐方案 A**——按 CLAUDE.md §3 "commit 拆开" 的精神，5 个 Step 拆 5 个 commit，每 commit 跑测试。

### 实施顺序

1. **Phase 3 先做**（独立，不依赖 UI）：
   - 写 `services/document_generator.py`（Word + PDF 统一接口）
   - 写 2 个 jinja2 模板（保守 + 现代）
   - 写 10-15 条单测覆盖 Word 输出（PDF 用前端方案，先做最小验证）
   - **测试驱动**：先写测试再写实现，确保 PDF 超页报错、Word 文件命名正确

2. **Phase 4 逐 Step 走**（按方案 A 渐进迁移）：
   - Step 1：保留 + 加 JD 三选一按钮（text 走 jd_parser.TextJDParser，image 走 ImageJDParser，rag 走 RAGJDRetriever）
   - Step 2：替换基础信息表单为渐进式披露（基本+教育+工作+项目+技能，每段 + 号扩展）
   - Step 3：复用 round-1 ResumeRewriter，加模式 A/B/auto 切换器（不动 backend）
   - Step 4：调 one_page_estimator 实时预估 + 瘦身向导
   - Step 5：调 document_generator 导出 Word + PDF（PDF 用 streamlit-html-to-pdf 或 print CSS）

3. **测试覆盖**（每 Step 加 3-5 条单测）：
   - Step 1：JD 三选一路由选择正确
   - Step 2：+ 号扩展/删除段正确，session_state 正确
   - Step 3：模式 A/B/auto 切换触发对应 service
   - Step 4：超页检测触发瘦身向导
   - Step 5：文件命名按 `{姓名}_{岗位}_{公司}` 格式正确

4. **手动场景 3 个**（按 update_plan §6 验收要求）：
   - 场景 1：完整简历（信息量 ≥ 70）→ Step 3 auto 选 A → Step 5 导出 Word
   - 场景 2：极简简历（信息量 < 40）→ Step 3 auto 选 B → Step 5 导出 Word（虚线框 + [AI 模板生成] 标注）
   - 场景 3：部分信息简历（40 ≤ 信息量 < 70）→ Step 3 auto 选 A+B → Step 5 导出 Word
   - **每个场景跑通截图 / 日志**，附在最终交付里

## 验收 checklist（按 update_plan §6）

完成后逐条勾选：

- [ ] Tab1（Step 2）表单填写流畅，`+` 号扩展正常
- [ ] Tab2（Step 1）三种 JD 输入都能跑通（含 OCR 校对环节）
- [ ] Tab3（Step 3）模式 A / 模式 B / 自动切换都能触发
- [ ] 模式 B 输出有"虚线框 + 警示色 + 标注"（前端 CSS class）
- [ ] 改写说明每段都生成，用户可见
- [ ] Tab4（Step 4）实时预估一页纸容量
- [ ] 超页触发瘦身向导，标黄 + AI 建议
- [ ] Tab5（Step 5）导出 Word / PDF，**强制一页**（超页报错）
- [ ] 模式 B 补全部分默认带 `[AI 补全]` 标记
- [ ] 文件命名自动 `{姓名}_{岗位}_{公司}.{ext}`
- [ ] pytest 全过，**当前 baseline 307**（round-1 后）+ 新增 ≥ 15
- [ ] 至少 3 个手动场景跑通，平均首次完成 < 10 分钟

## Commit 规范（按 CLAUDE.md §3 + update_plan §4.3）

**5 个 Phase 4 Step = 5 个 sub-commit**（方案 A 路径）。Phase 3 的 document_generator 单独成 1-2 个 commit。测试和文档各自 commit。

```
feat(M-rebuild-3): document_generator.py + Word 模板（保守/现代）
test(M-rebuild-3): document_generator 单测（≥ 10 条）
feat(M-rebuild-4): Step 1 JD 三选一入口
feat(M-rebuild-4): Step 2 渐进式披露表单
feat(M-rebuild-4): Step 3 模式 A/B/auto 切换器
feat(M-rebuild-4): Step 4 一页纸实时预览 + 瘦身向导
feat(M-rebuild-4): Step 5 Word/PDF 导出
test(M-rebuild-4): 5 个 Step UI 单测（≥ 15 条）
docs(M-rebuild-3+4): CHANGELOG 追加 [M-rebuild-3] + [M-rebuild-4] 两节
```

**不要一次性大 commit**——按 Step 拆。

## 推之前自检（按 update_plan §4.4.3）

1. `pytest tests/ -q` 必须 ≥ 307 + 新增测试全过
2. `git status` 确认无 `.env` / `*.db` / `data/cookies/*.json` / `*.bak` / `data/*.bak` 被 staged
3. pre-commit hook 已装（一次性 `bash tools/githooks/install.sh`）
4. 改了 `requirements.in` → `pip-compile` 生成 `requirements.lock` 同步推
5. `git log -1 --format='%an %ae'` 确认是本机作者

**注意**：本轮因账号迁移（旧账号已找不回），commit 在本地积累。**用户在 user message 里说了"先不考虑 push 的事情"**——所以本轮 commit 不 push，按 4.4.5 规则"本地积累" 等账号迁移完成再批量推。

## 已知歧义 / 需要用户拍板

启动前先看 update_plan.md 跟现状的冲突点（已知的）：

1. **Step 1 跟 update_plan §1.2 决策"JD 三选一"对不齐**：
   - update_plan 写的是"text/image/rag 三选一"
   - 现状 flow_a 第 1 步是"行业×职能×岗位"（RAG 的预选）
   - **怎么处理**？建议在 Step 1 保留"行业×职能×岗位"作为 RAG 入口，旁边加 text/image 两个备选按钮（3 个按钮 = text / image / 选岗位调 RAG）

2. **Word 模板套数**：update_plan 写 2-3 套，本轮做几套？
   - 建议先做 2 套（保守 + 现代），第 3 套创意留 round-3

3. **PDF 方案选型**：streamlit-html-to-pdf vs 浏览器打印 CSS vs weasyprint
   - update_plan 写"前端方案（react-to-print 或 html2pdf）"
   - 实际 streamlit 端有 `st.html` + 浏览器原生打印、也有 streamlit-pdf 之类第三方
   - **建议**：用 `st.components.v1.html` 嵌入 HTML + 浏览器 print-to-PDF，零依赖
   - 这个选型你定

4. **render_flow_a 改造方案**：方案 A（渐进迁移）还是方案 B（整体重写）
   - 建议方案 A

5. **跟 flow_b 的关系**：本轮要不要也升级 flow_b？还是只改 flow_a？
   - update_plan §1.1/§1.2 都是按 flow_a 写的
   - 建议本轮只动 flow_a，flow_b 保留

如果你在 user message 里看到这些问题已拍板，按 user 的来。否则**先看 update_plan.md + 现状 web_app.py 的 render_flow_a() 函数，再列歧义清单**问 Mavis（Mavis 帮你转给用户）。

## 启动指令

开始之前先做：

1. `cat update_plan.md` 通读（已要求必读，但再确认）
2. `git status` 看仓库状态
3. `pytest tests/ -q` 确认 baseline（应该是 **307 passed**，不是任务描述里的 81）
4. 把本 prompt 里的 5 个歧义先看 update_plan.md 和现状能不能解——能解的解掉，不能解的列出来返回 Mavis
5. 写实施计划（写到 update_plan §4.2 Phase 4 那一节里），包含：5 个 Step 的 commit 顺序 + 每个 Step 涉及的文件 + 测试覆盖
6. 实施计划写完**先给 Mavis 看，不要直接动手**

## 硬要求

- **不要嘴问"要不要推"**——按 4.4.5 规则，本轮 commit 都在本地积累，不 push
- **不要直接整体重写 render_flow_a()**——按方案 A 渐进迁移，5 个 Step 拆 5 个 commit
- **不要引 weasyprint / LibreOffice 等系统依赖**——PDF 走前端方案
- **不要新建 `services/jd_parser/` `services/resume_rewriter/` 等子目录**——保持扁平 *.py
- **不要删 v2.1 flow_b / 投递历史 / 我的简历 / JD 库**——只动 render_flow_a()
- **每个 Step 完成后跑 pytest tests/ -q** 确认 baseline 307 不破
- **3 个手动场景**（完整/极简/部分）跑通 + 截图/日志附最终交付

## 完成后给 Mavis 返回

- 改了哪些文件的列表（按 commit 分组）
- pytest 全过结果（行数 + 时间）
- §6 验收 checklist 12 条逐条勾选
- 3 个手动场景跑通日志/截图
- "没做/延后/需要拍板"列表
- update_plan.md 是否需要修订（如果有歧义解了 / 边界改了，更新文档）

**Mavis 会转给用户 review，再决定下一步**。
