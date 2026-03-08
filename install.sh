#!/usr/bin/env bash
# Install Claude Counter statusline for Claude Code.
#
# Usage:
#   ./install.sh          # Install and configure
#   ./install.sh --remove # Remove configuration

set -euo pipefail

SETTINGS_FILE="$HOME/.claude/settings.json"
COMMAND="uvx --from git+https://github.com/bonkey/claude-counter-statusbar claude-counter"

if [[ "${1:-}" == "--remove" ]]; then
    if [[ -f "$SETTINGS_FILE" ]]; then
        tmp=$(mktemp)
        python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    s = json.load(f)
s.pop('statusLine', None)
with open('$tmp', 'w') as f:
    json.dump(s, f, indent=2)
    f.write('\n')
"
        mv "$tmp" "$SETTINGS_FILE"
        echo "Removed statusLine from $SETTINGS_FILE"
    else
        echo "No settings file found at $SETTINGS_FILE"
    fi
    exit 0
fi

mkdir -p "$(dirname "$SETTINGS_FILE")"

if [[ -f "$SETTINGS_FILE" ]]; then
    tmp=$(mktemp)
    python3 -c "
import json
with open('$SETTINGS_FILE') as f:
    s = json.load(f)
s['statusLine'] = {
    'type': 'command',
    'command': '$COMMAND',
    'padding': 2
}
with open('$tmp', 'w') as f:
    json.dump(s, f, indent=2)
    f.write('\n')
"
    mv "$tmp" "$SETTINGS_FILE"
else
    python3 -c "
import json
s = {
    'statusLine': {
        'type': 'command',
        'command': '$COMMAND',
        'padding': 2
    }
}
with open('$SETTINGS_FILE', 'w') as f:
    json.dump(s, f, indent=2)
    f.write('\n')
"
fi

echo "Claude Counter statusline installed."
echo "  Config: $SETTINGS_FILE"
echo ""
echo "Restart Claude Code to see the statusline."
