#!/bin/bash
# Registers the AI Broker with Claude Code for THIS user (all projects) and installs the skill file. macOS / Linux version of register.bat.
# Nothing here runs by itself: you decide to run it.
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
echo
echo "This will run:"
echo "  claude mcp add ai-broker --scope user --env AIJOB_REQUESTER=claude -- \"$HERE/.venv/bin/python\" \"$HERE/mcp_launch.py\""
echo "and copy the skill to  $HOME/.claude/skills/ai-broker"
echo
read -r -p "Continue? [y/N] " ans
case "$ans" in y|Y) ;; *) exit 1;; esac
claude mcp add ai-broker --scope user --env AIJOB_REQUESTER=claude -- "$HERE/.venv/bin/python" "$HERE/mcp_launch.py" || exit 1
mkdir -p "$HOME/.claude/skills" && cp -R "$HERE/skill/ai-broker" "$HOME/.claude/skills/" && echo "skill copied"
echo
echo "Done. Open a NEW Claude Code session and ask:  \"what is in the AI queue?\""
read -r -p "Press Enter to close. " _
