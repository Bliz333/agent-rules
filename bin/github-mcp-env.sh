# Shared GitHub token env for local MCP clients.
# Source this file from shell startup files; it does not store the token.
if command -v gh >/dev/null 2>&1 && gh auth status --hostname github.com >/dev/null 2>&1; then
  __github_mcp_token="$(gh auth token --hostname github.com 2>/dev/null || true)"
  if [ -n "$__github_mcp_token" ]; then
    export GITHUB_PAT_TOKEN="$__github_mcp_token"
    export GITHUB_PERSONAL_ACCESS_TOKEN="$__github_mcp_token"
  fi
  unset __github_mcp_token
fi
