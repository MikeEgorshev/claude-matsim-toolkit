#!/usr/bin/env bash
# Install script for Claude MATSim Toolkit on macOS / Linux
# Usage: ./install/install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DST="$CLAUDE_DIR/skills/transport-modeling"
HOOKS_DST="$CLAUDE_DIR/hooks"

echo "Installing Claude MATSim Toolkit..."
echo "  Repo:   $REPO_ROOT"
echo "  Target: $CLAUDE_DIR"
echo

# 1. Skill
echo "[1/3] Copying skill -> $SKILLS_DST"
if [ -d "$SKILLS_DST" ]; then
    echo "      Existing skill found. Backup -> ${SKILLS_DST}.bak"
    rm -rf "${SKILLS_DST}.bak"
    mv "$SKILLS_DST" "${SKILLS_DST}.bak"
fi
mkdir -p "$(dirname "$SKILLS_DST")"
cp -R "$REPO_ROOT/skills/transport-modeling" "$SKILLS_DST"
echo "      OK"

# 2. Hook
echo "[2/3] Copying hook -> $HOOKS_DST"
mkdir -p "$HOOKS_DST"
cp "$REPO_ROOT/hooks/validate_matsim.py" "$HOOKS_DST/validate_matsim.py"
chmod +x "$HOOKS_DST/validate_matsim.py"
echo "      OK"

# 3. Settings snippet
echo
echo "[3/3] Register the hook in ~/.claude/settings.json"
echo
echo "Add this 'hooks' section to your settings.json:"
echo
cat <<EOF
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $HOOKS_DST/validate_matsim.py",
            "timeout": 15
          }
        ]
      }
    ]
  }
EOF
echo
echo "Done. Restart Claude Code to pick up changes."
