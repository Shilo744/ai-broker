#!/bin/bash
# Removes the AI Broker from Claude Code (macOS / Linux version of unregister.bat).
claude mcp remove ai-broker --scope user
rm -rf "$HOME/.claude/skills/ai-broker"
echo removed
read -r -p "Press Enter to close. " _
