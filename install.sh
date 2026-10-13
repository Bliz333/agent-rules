#!/usr/bin/env bash
# agent-rules 一键接入：把本仓的全局工作规范接到本机各 AI 工具的全局入口。
#
#   ./install.sh                 # 自动探测已安装的工具并接入
#   ./install.sh --dry-run       # 只显示会做什么，不写文件
#   ./install.sh --tools claude,opencode
#   ./install.sh --uninstall     # 移除本脚本写的托管块和 PATH 软链
#   ./install.sh --no-path       # 不把 project-docs 放进 PATH
#
# 所有改动都写在成对的托管标记之间，可重复执行、可整体卸载，不会动你已有的内容。
set -euo pipefail

BEGIN_MARK="# BEGIN agent-rules managed"
END_MARK="# END agent-rules managed"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULES_HOME="${AGENT_RULES_HOME:-$SCRIPT_DIR}"
GLOBAL_CORE="$RULES_HOME/global-core.md"
PROJECT_DOCS="$RULES_HOME/bin/project-docs"

DRY_RUN=0
UNINSTALL=0
INSTALL_PATH=1
TOOLS=""

TOOL_ORDER=(claude gemini opencode codex)

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

set_home() {
  RULES_HOME="$1"
  GLOBAL_CORE="$RULES_HOME/global-core.md"
  PROJECT_DOCS="$RULES_HOME/bin/project-docs"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-path) INSTALL_PATH=0 ;;
    --tools)
      [ $# -ge 2 ] || { echo "--tools 缺少取值" >&2; exit 2; }
      TOOLS="$2"; shift ;;
    --tools=*) TOOLS="${1#*=}" ;;
    --home)
      [ $# -ge 2 ] || { echo "--home 缺少取值" >&2; exit 2; }
      set_home "$2"; shift ;;
    --home=*) set_home "${1#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# 把源文件里去托管块后的内容写到 stdout；标记不成对时返回 3，避免误删用户内容。
strip_block() {
  awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
    $0 == b { if (open) bad = 1; open = 1; next }
    open && $0 == e { open = 0; next }
    open { next }
    { print }
    END { if (open || bad) exit 3 }
  ' "$1"
}

# 在文件里就地替换/追加托管块。参数：<文件> <块内容>
upsert_block() {
  local file="$1" block="$2" tmp
  tmp="$(mktemp)"
  if [ -f "$file" ] && grep -qF "$BEGIN_MARK" "$file"; then
    if ! strip_block "$file" > "$tmp"; then
      rm -f "$tmp"
      echo "错误：$file 里的 agent-rules 托管标记不成对，未改动它；请手动修好标记后重跑。" >&2
      return 1
    fi
  fi
  printf '%s\n%s\n%s\n' "$BEGIN_MARK" "$block" "$END_MARK" >> "$tmp"
  run mkdir -p "$(dirname "$file")"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[dry-run] 写入托管块到 %s\n' "$file"
    rm -f "$tmp"
  else
    mv "$tmp" "$file"
  fi
}

# 从文件里删除托管块。参数：<文件>
remove_block() {
  local file="$1" tmp
  [ -f "$file" ] || return 0
  grep -qF "$BEGIN_MARK" "$file" || return 0
  tmp="$(mktemp)"
  if ! strip_block "$file" > "$tmp"; then
    rm -f "$tmp"
    echo "警告：$file 里的 agent-rules 托管标记不成对，跳过，未改动。" >&2
    return 1
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[dry-run] 从 %s 移除托管块\n' "$file"
    rm -f "$tmp"
  else
    mv "$tmp" "$file"
  fi
  return 0
}

tool_present() {
  case "$1" in
    claude) [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1 ;;
    gemini) [ -d "$HOME/.gemini" ] || command -v gemini >/dev/null 2>&1 ;;
    opencode) [ -d "$HOME/.config/opencode" ] || command -v opencode >/dev/null 2>&1 ;;
    codex) [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1 ;;
  esac
}

tool_requested() {
  [ -z "$TOOLS" ] && return 0
  case ",$TOOLS," in *",$1,"*) return 0 ;; *) return 1 ;; esac
}

tool_config_path() {
  case "$1" in
    claude) echo "$HOME/.claude/CLAUDE.md" ;;
    gemini) echo "$HOME/.gemini/GEMINI.md" ;;
    opencode) echo "$HOME/.config/opencode/AGENTS.md" ;;
    codex) echo "$HOME/.codex/AGENTS.md" ;;
  esac
}

# 各工具接法：支持 @ 导入的用导入行；只认 AGENTS.md 的用「先读本文件」指引块。
tool_block() {
  case "$1" in
    claude|gemini)
      printf '%s\n' "@$GLOBAL_CORE"
      ;;
    *)
      printf '%s\n' \
        "## 全局 AI 工作规范（agent-rules）" \
        "" \
        "本机全局 AI 工作规范在 \`$GLOBAL_CORE\`。" \
        "开始任何任务前先完整读取该文件，并在整个任务中遵守它；" \
        "项目 / 模块的 \`AGENTS.md\` 只补充项目事实，冲突时以全局规范为准。"
      ;;
  esac
}

install_path_link() {
  local target="" candidate
  for candidate in "$HOME/.local/bin" "$HOME/bin"; do
    case ":$PATH:" in
      *":$candidate:"*) target="$candidate/project-docs"; break ;;
    esac
  done
  if [ -z "$target" ]; then
    target="$HOME/.local/bin/project-docs"
    say "提示：~/.local/bin 和 ~/bin 都不在 PATH，已链接但仍需手动把该目录加进 PATH。"
  fi
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    say "跳过 PATH 软链：$target 已存在且不是软链。"
    return 0
  fi
  run mkdir -p "$(dirname "$target")"
  run ln -sfn "$PROJECT_DOCS" "$target"
  say "已把 project-docs 链到 $target"
}

remove_path_link() {
  local candidate
  for candidate in "$HOME/.local/bin/project-docs" "$HOME/bin/project-docs"; do
    if [ -L "$candidate" ]; then
      run rm -f "$candidate"
      say "已移除 $candidate"
    fi
  done
}

say "agent-rules 规则目录：$RULES_HOME"
if [ "$RULES_HOME" != "$HOME/.agent-rules" ]; then
  say "注意：这不是默认安装位置；需要时在 shell 启动文件里 export AGENT_RULES_HOME=\"$RULES_HOME\"。"
fi
[ -f "$GLOBAL_CORE" ] || { echo "找不到 $GLOBAL_CORE" >&2; exit 1; }

if [ "$UNINSTALL" -eq 1 ]; then
  skipped=0
  for tool in "${TOOL_ORDER[@]}"; do
    tool_present "$tool" || continue
    if ! remove_block "$(tool_config_path "$tool")"; then
      skipped=1
    fi
  done
  [ "$INSTALL_PATH" -eq 1 ] && remove_path_link
  if [ "$skipped" -eq 1 ]; then
    say "卸载完成，但有文件的托管标记不成对已被跳过，请按上面的警告手动处理。"
  else
    say "卸载完成，托管块已移除。"
  fi
  exit 0
fi

[ -f "$PROJECT_DOCS" ] || say "提示：没找到 $PROJECT_DOCS，project-docs 可能不可用。"

wired=0
for tool in "${TOOL_ORDER[@]}"; do
  tool_requested "$tool" || continue
  if ! tool_present "$tool"; then
    [ -n "$TOOLS" ] && say "未探测到 $tool，跳过。"
    continue
  fi
  upsert_block "$(tool_config_path "$tool")" "$(tool_block "$tool")"
  say "已接入 $tool → $(tool_config_path "$tool")"
  wired=$((wired + 1))
done
[ "$wired" -eq 0 ] && say "没有探测到已安装的工具；可用 --tools claude,gemini,opencode,codex 指定。"

[ "$INSTALL_PATH" -eq 1 ] && install_path_link

cat <<EOF

下一步：
  1. 开一个新的 AI 会话（或重启工具），让它读一遍 $GLOBAL_CORE。
  2. 进到任意项目，让 AI 跑：project-docs bootstrap --repo .
  3. 想改规则，直接改 $GLOBAL_CORE；重新跑本脚本可安全覆盖托管块。
EOF

if [ "$DRY_RUN" -eq 1 ]; then
  say "（dry-run 什么都没写）"
fi
