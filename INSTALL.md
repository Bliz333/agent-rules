# INSTALL —— 手动安装与进阶配置

## 依赖

- `bash`（安装脚本）
- `git`（克隆仓库）
- `python3`（`project-docs` 检查工具；建议 3.9+）

## 安装

```bash
git clone https://github.com/Bliz333/agent-rules ~/.agent-rules
~/.agent-rules/install.sh
```

`install.sh` 默认会：

1. 探测本机已安装的工具（Claude Code / Gemini CLI / OpenCode / Codex），只接入探测到的。
2. 往每个工具的全局入口文件写一段托管块（成对的 `# BEGIN/END agent-rules managed` 标记）。
3. 把 `project-docs` 软链到 `~/.local/bin` 或 `~/bin`（若该目录在 PATH 中）。

它**不会**覆盖你已有的内容：托管块之外的文字原样保留；重复执行只替换托管块；`--uninstall` 整体移除。

### 常用参数

| 参数 | 作用 |
|---|---|
| `--dry-run` | 只打印会做什么，不写任何文件 |
| `--tools claude,opencode` | 只接入指定工具 |
| `--uninstall` | 移除托管块和 PATH 软链 |
| `--no-path` | 不把 `project-docs` 放进 PATH |
| `--home <路径>` | 指定规则仓库位置（等价于 `AGENT_RULES_HOME`） |

### 各工具接法

| 工具 | 入口文件 | 写入内容 |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `@<RULES_HOME>/global-core.md` 导入行 |
| Gemini CLI | `~/.gemini/GEMINI.md` | `@<RULES_HOME>/global-core.md` 导入行 |
| OpenCode | `~/.config/opencode/AGENTS.md` | 「先读 global-core.md」指引块 |
| Codex CLI | `~/.codex/AGENTS.md` | 「先读 global-core.md」指引块 |

> OpenCode V2 的 `instructions` 配置项不会加载文件，它只认 `AGENTS.md`，所以这些工具用指引块而不是导入行。指引块要求模型在开工前读取 `global-core.md`。

其它工具手动接入：把 `global-core.md` 的路径挂到它的全局规则位置，或用与上表相同风格的指引。

## project-docs

```bash
# 在任意项目里生成 / 更新最小知识地图（不会覆盖已有 AGENTS.md）
project-docs bootstrap --repo .

# 检查：泄密、断链、占位符、文档膨胀、工具桥接
project-docs doctor --repo .
project-docs doctor --repo . --base <任务基线>   # 额外列出受影响的 AGENTS.md
```

- `project-docs` 可放在任何目录；它按自身位置解析 OK，默认安装目录是 `~/.agent-rules`。
- 接入后，项目里会有一份自包含的 `.github/project-docs/project-docs` 副本；`doctor` 可独立运行，`bootstrap` 会转交给可信上游。
- 上游位置解析顺序：环境变量 `PROJECT_DOCS_SOURCE` → PATH 上的 `project-docs` → `$AGENT_RULES_HOME/bin/project-docs`（默认 `~/.agent-rules`）。
- 安装到非默认目录时，在 shell 启动文件里导出即可：

```bash
export AGENT_RULES_HOME="$HOME/path/to/agent-rules"
```

## OpenCode 可选工具

`tools/opencode/` 里有可选的 OpenCode 增强，手动取用：

- `tools/opencode/permissions.example.json` —— 一套 `permissions` 分级示例（破坏性命令 ask / 危险命令 deny）。
- `tools/opencode/agents/review.md` —— 一个只读的 `review` 子代理，用于在候选完成后做一次终审。**里面的 `model` 是占位，改成你自己配置的模型。**

把它们并入你的 `~/.config/opencode/`（注意 `agents/` 目录位置），不要直接覆盖现有文件。

## 经验记忆层（可选）

`global-core.md` 支持接入一个跨项目的经验记忆后端，但**不内置任何服务**。想接自己的后端见 [docs/ai/memory-layer.md](docs/ai/memory-layer.md)。

## 杂项脚本

- `bin/github-mcp-env.sh` —— 从 `gh` 取 GitHub token 并导出成 `GITHUB_PAT_TOKEN` / `GITHUB_PERSONAL_ACCESS_TOKEN`，供本地 MCP 客户端复用。在 shell 启动文件里 `source` 它即可；它本身不存储 token。

## 卸载

```bash
~/.agent-rules/install.sh --uninstall   # 移除托管块与软链
rm -rf ~/.agent-rules                    # 删规则仓库
```

项目里由 `bootstrap` 生成的 `.github/project-docs/`、根 `AGENTS.md`、`.agents/` 需要各自在项目里删除——本脚本不碰项目文件。

## 排错

- **装完 AI 没按规范来**：开一个新的会话（部分工具只在会话开始读全局规则）；确认入口文件里的托管块指向的 `global-core.md` 路径存在。
- **`project-docs` 命令找不到**：软链目录不在 PATH。手动加 `~/.local/bin` 到 PATH，或用绝对路径 `~/.agent-rules/bin/project-docs`。
- **vendor 的 bootstrap 报找不到上游**：设 `PROJECT_DOCS_SOURCE` 或导出 `AGENT_RULES_HOME`。
- **`bootstrap` 拒绝写入**：你在受保护主线（`main`/`master`/`develop`）上。按 `global-core.md` 先开专用 worktree / 任务分支。
