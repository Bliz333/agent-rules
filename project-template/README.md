# 跨工具项目文档生命周期

`project-docs` 让新项目从第一次实际修改开始形成与规模相称的知识地图,不要求人工复制模板或维护独立记忆。

```bash
# AI 在专用 worktree / 任务分支内执行
~/.agent-rules/bin/project-docs bootstrap --repo .
~/.agent-rules/bin/project-docs doctor --repo . --base <任务基线>
```

接入后也可从项目内运行 `.github/project-docs/project-docs bootstrap --repo .`;vendored
入口会转交给 `PROJECT_DOCS_SOURCE` 指定的可信上游,默认使用
`~/.agent-rules/bin/project-docs`(安装到别处时用 `PROJECT_DOCS_SOURCE` 指定)。`doctor`
本身始终可由 vendored 副本独立运行。

## bootstrap

- 从 Git、manifest、CI 和目录结构收集可验证事实。
- 缺少时创建根 `AGENTS.md`、薄 `CLAUDE.md` / `GEMINI.md` 桥接、`.agents/local/` 忽略规则和适用的 GitHub 文档门禁;checker 随目标仓库提交,不依赖访问私有跨仓库 Action。
- 已接入且目标为仓库默认分支的标准 PR,由 `pull_request_target` 使用事件时的默认分支可信 checker 以 `--strict` 检查候选内容;特权检查把候选 checkout 只当数据,永不执行候选 checker。非默认 base 会在 checkout 前明确失败;PR 改 base 时会重新检查。首次接入 PR 的 base 尚无该 workflow,必须靠独立审查并满足全局标准 PR 自动收口门槛后完成安装。
- 内置 workflow 只提供辅助证据,**不得直接配置为 required hard gate**:`pull_request_target` 状态不绑定 PR head,形似 SHA 的分支可能不触发该事件,Merge Queue 还需要 `merge_group`。需要 fail-closed 门禁时,另行配置受独立身份约束的 GitHub App 或组织级 required workflow。详见 [GitHub 事件限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)。
- workflow 不监听 `push`,不会执行分支内可变 checker。checker / 固定 workflow 有变更时默认失败;独立审查精确提交后,由有仓库写权限的维护者**刚刚加上** `project-docs-upgrade-reviewed` 标签才会改用“旧可信 checker 严格检查其余候选内容”的升级路径,候选 checker 仍不会执行。任何后续 push 都会重新失败;必须审查新 head 后移除并重加标签。标签与 review 条件满足后按全局标准 PR 自动收口门槛直接合入,不再增加人工 Git 审批。
- 永不覆盖已有 `AGENTS.md`,不创建空 `docs/ai/`、历史归档或记忆日志。
- 在已有提交的受保护主线上拒绝写入;`--dry-run` 始终可用。

## doctor

- 阻断断链、模板占位符、高置信度凭据、错误工具桥接和未忽略的 `.agents/local/`。
- 告警根/模块/领域文档过长、孤儿领域文档和公开 IP;`--strict` 可把告警升级为失败。
- 传 `--base` 时列出本次变更适用的祖先 `AGENTS.md`,供 AI 做任务范围内的文档影响检查。

## 分层

| 层 | 位置 | 职责 |
|---|---|---|
| 全局 | `~/.agent-rules/global-core.md` | 多工具共享工作规范 |
| 项目入口 | 根 `AGENTS.md` | 精简知识地图与跨模块事实 |
| 工具桥接 | 根 `CLAUDE.md` / `GEMINI.md` | 导入 `AGENTS.md` + 极少工具专属内容 |
| 模块 | 子目录 `AGENTS.md` | 仅该子树适用的规则 |
| 领域 | `docs/ai/*.md` | 非显然架构、运维、失败模式和验证知识 |
| 本地敏感值 | `.agents/local/` | gitignored 主机、凭据路径和环境真值 |

`MODULE_AGENTS.md` 与 `DOMAIN.md` 是按需参考模板,bootstrap 不会批量复制它们。所有项目事实仍只存在于目标仓库 checked-in Markdown,没有工具私有知识库。
