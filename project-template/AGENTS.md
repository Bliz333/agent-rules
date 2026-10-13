<!-- project-docs: template -->
# {{PROJECT_NAME}} - 项目知识地图
<!-- project-docs: generated -->

> 能直接读取 `AGENTS.md` 的 coding 工具读本文件;Claude / Gemini 分别经 `CLAUDE.md` / `GEMINI.md` 引入同一份规则。
> 全局 worktree、Git、安全与自治规则见 {{GLOBAL_CORE_PATH}},本文件只记录项目事实。
> 敏感真值只放在 gitignored `.agents/local/`;checked-in 文档只写抽象引用。

## 读取顺序

1. 先读本文件。
2. 修改某条路径时,只继续读取其祖先链上适用的 `AGENTS.md`,停在最近一层。
3. 仅在任务命中知识地图主题时读取对应 `docs/ai/*.md`,不预加载无关文档。

## 项目边界

- 技术栈:{{TECHNOLOGIES}}
{{SOURCE_AREAS}}

## 验证入口

{{VALIDATION_COMMANDS}}
{{CI_PATHS}}

## 知识地图

- 当前没有需要单独下沉的领域文档。只有出现非显然、稳定且会影响后续实现的知识时,才创建 `docs/ai/<area>.md` 并在这里增加一行路由。

## 模块规则

- 当前没有证实需要独立规则的模块。只有子树存在不同于项目级的约束时,才在该子树创建 `AGENTS.md` 并在这里登记。

## Git 与交付

- 远端默认主线:{{DEFAULT_BRANCH}}
- worktree、受保护主线、commit / push 与不可逆操作边界统一遵循 {{GLOBAL_CORE_PATH}}。

## 文档维护

- 只记录代码、配置或验证已经证明的事实;不提交猜测、占位符、任务流水账或可直接从代码得到的清单。
- 任务结束前运行 {{DOCTOR_COMMAND}};只修正本次证实过时或缺失的内容。若主线未识别,有明确任务基线时再追加 `--base <commit>`。
