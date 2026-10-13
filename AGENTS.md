# agent-rules - 项目知识地图
<!-- project-docs: generated -->

> 能直接读取 `AGENTS.md` 的 coding 工具读本文件;Claude / Gemini 分别经 `CLAUDE.md` / `GEMINI.md` 引入同一份规则。
> 本仓对外分发;全局工作规范见 `~/agent-rules/global-core.md`,本文件只记录本仓事实。
> 敏感真值只放在 gitignored `.agents/local/`;checked-in 文件只写抽象引用。

## 读取顺序

1. 改全局规则或安装行为,先读 `global-core.md`。
2. 改项目文档生命周期工具时,再读 `bin/project-docs`、`project-template/` 与 `tests/test_project_docs.py`。
3. 不为全面了解而读取无关文件。

## 项目边界

- 本仓是**分发件**,不含应用运行时,包含:多工具共享工作规范 `global-core.md`、接入脚本 `install.sh`、给 AI 的安装提示词 `SETUP_PROMPT.md`、项目文档检查工具 `bin/project-docs` + `project-template/`、可选 OpenCode 模板 `tools/opencode/`。
- 面向他人使用:任何面向用户的文本都不得写死本机路径、私人项目名或凭据。安装位置用环境变量 `AGENT_RULES_HOME` 覆盖,默认 `~/.agent-rules`。
- 跨项目经验记忆层**不内置任何后端**,只约定接口与隐私红线,见 `docs/ai/memory-layer.md`。

## 跨模块不变量

- `bin/project-docs` 是项目文档生命周期的唯一机械接口;外部只依赖 `bootstrap` 与 `doctor`。
- 项目里 vendor 的 `.github/project-docs/project-docs` 必须与 `bin/project-docs` 逐字节一致;本仓自己由 `bootstrap` 生成,改动 `bin/project-docs` 后需同步该副本。
- `bootstrap` 不覆盖已有 `AGENTS.md`,不在已有提交的受保护主线上写入,不创建空领域文档。
- `doctor` 只阻断确定性错误;结构、大小和低置信度敏感信息保持告警,除非显式 `--strict`。
- 模板资产中的 `project-docs: template` 标记允许保留渲染变量;生成到目标仓库时必须移除标记和全部变量。

## 验证入口

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v`
- `bash -n install.sh bin/github-mcp-env.sh`
- `./bin/project-docs doctor --repo . --base origin/main`
<!-- project-docs: ci-start -->
- CI 配置:`.github/workflows/project-docs.yml`;CI 提供自动验证证据,内置 project-docs workflow 只辅助检查目标为默认分支的 PR,不是合并硬门禁。
<!-- project-docs: ci-end -->
- 本仓没有付费 CI;上面三条就是本地门禁。

## 知识地图

- `docs/ai/memory-layer.md` — 可选跨项目经验记忆层:接口约定、如何接自己的后端、隐私红线。被问到「要不要接记忆 / 怎么接」时读它。

## 模块规则

- 当前没有需要单独下沉的模块规则。

## Git 与交付

- 远端默认主线 `main`;在主线 checkout 只读,所有修改走专用 worktree 与任务分支。
- 任务分支 commit、push、PR、按风险档要求的 code review、合入 `main` 与合入后验证,按 `global-core.md` 的标准 PR 自动收口门槛自主完成。

## 文档维护

- 只记录代码、配置或验证已经证明的事实;不提交猜测、占位符或任务流水账。
- 任务结束前运行 `~/agent-rules/bin/project-docs doctor --repo .`;只修正本次证实过时或缺失的内容。
