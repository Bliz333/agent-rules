# SETUP_PROMPT —— 复制给 AI 就能自动配置

把下面整段（从「你是安装助手」到结尾）复制到任意 AI 编码工具里发给它。它会自己克隆、安装、验证。

````text
你是 agent-rules 的安装助手。请按下面步骤在本机完成安装并验证，全程自主完成，不要逐步问我。

背景：agent-rules 是一套跨工具共享的 AI 编码工作规范仓库，地址
https://github.com/Bliz333/agent-rules 。它的 install.sh 会把仓库里的
global-core.md 接到各 AI 工具的全局入口，幂等、可卸载、不会覆盖我已有的内容。

步骤：

1. 确定安装目录：默认 `~/.agent-rules`。如果我已经把仓库放在别处，
   用我告诉你的路径；没告诉就用默认。设 RULES_HOME 指到它。

2. 如果 RULES_HOME 还不存在，克隆仓库：
   `git clone https://github.com/Bliz333/agent-rules "$RULES_HOME"`。
   如果已存在且是 git 仓库，先 `git -C "$RULES_HOME" pull --ff-only` 再继续；
   如果存在但不是仓库，停下来问我，不要覆盖。

3. 先看它会做什么，再执行：
   `bash "$RULES_HOME/install.sh" --dry-run`
   `bash "$RULES_HOME/install.sh"`

4. 验证：
   - 完整读一遍 `$RULES_HOME/global-core.md`。
   - 检查本次接入的每个工具全局入口文件里，都有一段
     `# BEGIN agent-rules managed` … `# END agent-rules managed`，内容指向 global-core.md。
   - 确认 `command -v project-docs` 能找到命令（找不到就说明软链目录不在 PATH）。

5. 如果 RULES_HOME 不是默认的 `~/.agent-rules`，告诉我需要在 shell 里
   `export AGENT_RULES_HOME="<实际路径>"`（并说明加进 shell 启动文件更省事）。

6. 汇报：用中文，半结构化——先一句话结果，再说装了哪些工具的哪个文件、
   验证是否通过、有没有需要我手动做的一步。不要贴大段命令输出。

约束：
- 只运行上面这些命令；不要顺手改我的其它配置，不要提交或推送任何东西。
- 拿不准（比如 RULES_HOME 已有非仓库目录、权限不足）就停下来问我，不要猜。
````

## 为什么要写成提示词

「让 AI 自己装」比「让用户照着 README 敲」可靠：AI 能处理路径选择、已存在仓库、PATH、权限这些分支，也能验证装完真的生效。

安装脚本本身也支持手动使用，参数见 [INSTALL.md](INSTALL.md)。
