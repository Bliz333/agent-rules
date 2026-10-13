# agent-rules

一套**跨工具共享的 AI 编码工作规范**。写一份规则，Claude Code、Gemini CLI、OpenCode、Codex 都遵守；再配一个能自动生成"项目知识地图"的检查工具，让 AI 在每个仓库里都按同一套纪律干活。

**给用户的一句话用法**：把下面这段发给你正在用的 AI，它自己会装好。

> 帮我安装 agent-rules：把 https://github.com/Bliz333/agent-rules 克隆到 `~/.agent-rules`，
> 然后阅读其中的 `SETUP_PROMPT.md` 并按它完成配置。

---

## 它解决什么

- **规则散、各工具各写一套** → 一份 `global-core.md` 当唯一真相源，各工具入口只引用它。
- **AI 乱问、把机械活丢回给人** → 明确"哪些必须自主做完、哪些才需要人看一眼"。
- **AI 顺手把代码改膨胀、文档写成仓库** → 交付范围门禁 + 文档反膨胀门禁。
- **每个新仓库 AI 都要重新摸索** → `project-docs` 自动生成根 `AGENTS.md` 知识地图并检查健康度。

## 30 秒上手

**方式 A（推荐，交给 AI）**：把上面那段提示词发给任意 AI 编码工具，它读完 `SETUP_PROMPT.md` 会自动克隆、安装、验证。

**方式 B（自己装）**：

```bash
git clone https://github.com/Bliz333/agent-rules ~/.agent-rules
~/.agent-rules/install.sh          # 自动探测已安装的工具并接入
```

装完开一个新的 AI 会话，让 AI 读一遍 `~/.agent-rules/global-core.md` 即可生效。

## 装了什么

| 部件 | 作用 |
|---|---|
| `global-core.md` | 全局工作规范（自治边界、worktree、Git 安全、汇报方式、子代理纪律） |
| `install.sh` | 一键把规范接到各工具的全局入口，幂等、可卸载 |
| `SETUP_PROMPT.md` | 复制给 AI 就能自动配置的提示词 |
| `bin/project-docs` | 项目知识地图的生成 / 检查工具：`bootstrap` 与 `doctor` |
| `project-template/` | 项目 / 模块 / 领域文档模板 |
| `tools/opencode/` | 可选的 OpenCode 权限策略与只读 `review` agent 模板 |
| `docs/ai/` | 进阶说明（如可选的经验记忆层） |

## 支持的工具

| 工具 | 全局入口 | 接法 |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `@` 导入 |
| Gemini CLI | `~/.gemini/GEMINI.md` | `@` 导入 |
| OpenCode | `~/.config/opencode/AGENTS.md` | 指引块 |
| Codex CLI | `~/.codex/AGENTS.md` | 指引块 |

其它工具（Cursor / Windsurf / Cline / Aider 等）手动把 `global-core.md` 挂到它的全局规则位置即可；机制一样。

## 一个例子：新项目自动接上

在任意已有仓库里，让 AI 跑：

```bash
~/.agent-rules/bin/project-docs bootstrap --repo .
```

它会读出技术栈、验证命令、CI 路径，生成精简的根 `AGENTS.md` 知识地图；之后每次提交前用 `doctor` 检查有没有泄密、断链、占位符或文档膨胀。

## 约定

- **语言**：默认简体中文输出，可在 `global-core.md` 里改成别的语言。
- **路径**：默认装到 `~/.agent-rules`，可用环境变量 `AGENT_RULES_HOME` 覆盖。
- **经验记忆层**（可选）：不内置任何后端；想接自己的记忆服务见 `docs/ai/memory-layer.md`。

## 许可

MIT，见 [LICENSE](LICENSE)。
