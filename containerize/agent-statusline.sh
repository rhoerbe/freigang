#!/usr/bin/env bash
# Claude Code statusline for freigang agent container
# Input: JSON from Claude Code via stdin
# Output: formatted status string

input=$(cat)

cwd=$(echo "$input" | jq -r '.cwd // .workspace.current_dir // empty')
model=$(echo "$input" | jq -r '.model.display_name // empty')
ctx_used=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
cost=$(echo "$input" | jq -r '.session.total_cost_usd // empty')

repo=""
if [[ -n "$cwd" ]]; then
    repo=$(echo "$cwd" | sed 's|^/workspace/||' | cut -d'/' -f1)
fi

out=""
[[ -n "$repo" ]] && out="${repo}"
out="${out} $(whoami)"
[[ -n "$model" ]] && out="${out} | ${model}"
[[ -n "$ctx_used" ]] && out="${out} | ctx:$(printf '%.0f' "$ctx_used")%"
[[ -n "$cost" ]] && out="${out} | \$$(printf '%.4f' "$cost")"

printf '%s' "$out"
