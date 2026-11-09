"""Launcher for the MCP server that works from any working directory (Claude Code starts MCP servers in the project folder)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aibroker.mcp_server import main
main()
