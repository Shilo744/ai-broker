@echo off
rem Registers the AI Broker with Claude Code for THIS Windows user (all projects), and installs the skill file.
rem Nothing here runs by itself: the owner decides to double-click it.
set "HERE=%~dp0"
echo.
echo This will run:
echo   claude mcp add ai-broker --scope user --env AIJOB_REQUESTER=claude -- "%HERE%.venv\Scripts\python.exe" "%HERE%mcp_launch.py"
echo and copy the skill to  %USERPROFILE%\.claude\skills\ai-broker
echo.
choice /m "Continue"
if errorlevel 2 exit /b 1
claude mcp add ai-broker --scope user --env AIJOB_REQUESTER=claude -- "%HERE%.venv\Scripts\python.exe" "%HERE%mcp_launch.py"
xcopy /E /I /Y "%HERE%skill\ai-broker" "%USERPROFILE%\.claude\skills\ai-broker" >nul && echo skill copied
echo.
echo Done. Open a NEW Claude Code session and ask:  "what is in the AI queue?"
pause
