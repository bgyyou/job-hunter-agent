# Job Hunter 项目协作规则

## 1. 第一性原理（继承自全局）
以第一性原理出发，从原始需求和问题本质出发，不从惯例或模版出发。
- 目标不清晰时停下来讨论，不要假设用户清楚想要什么。
- 路径不是最短的，直接说并建议更好的办法。
- 遇到问题追根因，不打补丁。

## 2. 沟通偏好
- 中文回复，简洁，先结论再细节。
- 不做向后兼容 hack（不留 alias、不保留废弃字段、不写"removed"占位注释）。一次性硬切。

## 3. 自动迭代与同步铁律（重点）
每次完成一轮有意义的迭代（修了 bug / 加了功能 / 改了配置 / 跑通了 workflow）后，**主动执行以下三步**，不等用户提醒：

```bash
pytest tests/ -q                    # 1. 本地测试先过
git add <具体文件>                   # 2. 别 git add -A
git commit -m "<type>(<scope>): <一句话 why>"
git push                            # 3. 推到 GitHub，触发 CI
```

### 判断标准
- ✅ 该推：修了 bug、加了功能、改了配置、更新了文档、CI 修复
- ❌ 不该推：临时调试 print、本地 `.env` 改动（gitignored）、一次性验证脚本

判断一句话：**这个 commit 三个月后回来看，能否解释清楚改了啥、为什么**。解释不清就别推。

### Commit message 风格（沿用本仓库已有惯例）
- `feat(M6): ...` — 新功能，M6 是里程碑编号
- `fix(M2.5.4): ...` — bug 修复
- `refactor(N7): ...` — 重构，N7 是批次编号
- `ci: ...` — CI/CD 改动
- `docs: ...` — 纯文档
- `test: ...` — 纯测试

### 推之前自检
1. `pytest tests/ -q` 必须 81 passed（或当前基线）
2. `git status` 确认没有 `.env` / `*.db` / `data/cookies/*.json` 等被意外 staged
3. pre-commit hook 已装（`bash tools/githooks/install.sh` 一次性）

### 推之后
GitHub Actions 会自动跑 `tests` + `secret-scan`。如果失败：
1. `gh run list --limit 3` 看哪条挂了
2. `gh run view <id> --log-failed` 拿日志
3. 修完按上面三步再推一次，不要 force push

## 4. LLM 配置
代码 provider-neutral，环境变量是 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_USE_ANTHROPIC_FORMAT`。
当前默认接 Agnes（apihub.agnes-ai.com）。切回火山引擎 / OpenAI / DeepSeek 只改 `.env` 这四个变量，不改代码。

## 5. 数据库
- 默认 SQLite（`data/jobhunter_v2.db`），零配置。
- 进阶 PostgreSQL+pgvector：`docker compose up -d postgres` + 改 `.env` 的 `DATABASE_URL`。

## 6. 禁区
- 绝对禁止读取 PDF / Word / PPT 二进制文档（火山引擎兼容性约束）。提醒用户先用 PaddleOCR 等工具提文字。
- `.env` 永远不进 git。pre-commit hook 会拦 `sk-*` 形式硬编码 key。
- 不擅自调高 `CRAWLER_DAILY_LIMIT`，遵守目标站 robots.txt。

## 7. 治理入口
- 完整变更账本：`CHANGELOG_v2.1.md`（每个里程碑/批次追加一节）
- 升级 schema：在 `database/migrations/` 新增编号文件
- 贡献者流程：`CONTRIBUTING.md`
