@echo off
rem Opens Claude Code inside the AI Broker folder with the broker's MCP tools and its assistant instructions loaded.
rem Nothing in your Claude settings is changed: the MCP config and prompt are passed on the command line for this session only.
chcp 65001 >nul
cd /d "%~dp0.."
title AI Broker + Claude
claude --mcp-config "%CD%\mcp.json" --append-system-prompt-file "%CD%\skill\ai-broker\AGENT_PROMPT.md" --add-dir "%CD%\output"
