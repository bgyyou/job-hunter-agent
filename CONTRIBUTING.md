# 贡献指南

感谢你愿意改进 Job Hunter！本文是对外贡献者的最短可行流程，三分钟读完就能开 PR。

## 1. 本地开发环境

```bash
git clone https://github.com/<你的 fork>/job-hunter-agent.git
cd job-hunter-agent
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.lock
pip install -r requirements-dev.in    # ruff / interrogate / pip-tools

# 配置自己的 API Key（不要用任何"公共 demo key"——没有这种东西）
cp .env.example .env
# 编辑 .env，把 VOLCANO_API_KEY 替换成你自己的

# 装 pre-commit 钩子（拦截 sk-XXX / .env 误提交）
bash tools/githooks/install.sh

# 跑一遍测试，确认基线
pytest tests/ -q
```

## 2. 改代码前先跑测试

```bash
pytest tests/ -v
```

baseline 应该是 **35 passed**。如果你环境里就有失败用例，先排查环境差异，不要在它失败的基础上叠加改动。

## 3. 提交规范

提交信息用动宾结构，前缀帮助 reviewer 一眼定位影响范围：

```
feat(crawler): 新增 51job 站点适配器
fix(rag): chunker 在标题为空时崩溃
docs(readme): 修正 pgvector 升级步骤
test(repository): 补 insert_match 边界用例
chore(deps): 升级 streamlit 到 1.40
refactor(web_app): 抽出 Tab3 的匹配渲染函数
```

scope 用模块名（`crawler` / `rag` / `web_app` / `repository` 等），不要写 "all" / "misc"。

每次 commit 都会触发本地 pre-commit 钩子检查密钥泄露，**不要用 `--no-verify` 绕过**。如果误报，开 issue 讨论怎么改 `.gitleaks.toml`，不要静默跳过。

## 4. PR 自检清单

开 PR 前自查这五条：

- [ ] `pytest tests/ -q` 全过（35+，看你新增了几条）
- [ ] 改了 `requirements.in` → 跑 `PYTHONUTF8=1 pip-compile --output-file=requirements.lock --strip-extras requirements.in`，把 lock 一起提交
- [ ] 改了 public 函数 → 加/更新 docstring（CI 会跑 `interrogate`，阈值 80%）
- [ ] 改了爬虫 → 在 PR 描述里附一段实际抓取的日志片段（脱敏）
- [ ] PR 描述说清楚：**为什么** 改（不要只写"什么"）

## 5. 不收的 PR

为了节省彼此时间，下面这类 PR 默认会被关闭：

- 把任何"公共 / 内置 / demo" API Key 加回代码里
- 关掉 pre-commit 钩子或改 `.gitleaks.toml` 的 allowlist 让 `sk-` 真 key 通过
- 大规模代码重排（rename / 移文件）但不解释动机
- 只改格式不改语义，且没跑 `ruff format`
- 给爬虫加更激进的并发/无视 robots.txt 的开关

## 6. 报 issue

模板很简单：

- **环境**：OS / Python 版本 / 是否走 Docker Postgres
- **复现步骤**：从 `streamlit run web_app.py` 开始的最小路径
- **期望**：你以为会发生什么
- **实际**：实际发生了什么（带日志片段，脱敏）

爬虫相关的 issue 请说明站点名 + 关键词 + `--limit`，不要附 cookies。

## 7. 长程演进

每个里程碑都追加在 `CHANGELOG_v2.1.md`，对照修订 README 里的项目结构图。schema 变更走 `database/migrations/` 编号文件，不要直接改 `schema_pg.sql`。

有问题先翻 `CLAUDE.md` 的"第一性原理"原则——不知道为什么要做的事，就不要做。
