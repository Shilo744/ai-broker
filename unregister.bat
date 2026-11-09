@echo off
claude mcp remove ai-broker --scope user
rmdir /S /Q "%USERPROFILE%\.claude\skills\ai-broker" 2>nul
echo removed
pause
