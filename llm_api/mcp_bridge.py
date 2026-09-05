import asyncio
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List

from config.settings import Settings
from wren_setup.mcp_config import build_mcp_config, wren_executable

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from mcp.types import CallToolResult, Tool

from contextlib import asynccontextmanager

class WrenMCPBridge:
    def __init__(self, config_name: str, privacy_mode: str, settings: Settings):
        self.config_name = config_name
        self.privacy_mode = privacy_mode
        self.settings = settings
        
        # Build the exact same env and args as the CLI would use
        config = build_mcp_config(config_name, privacy_mode, settings)
        server_config = config["mcpServers"]["wren"]
        
        self.command = server_config["command"]
        self.args = server_config["args"]
        self.env = server_config["env"]
        
        # We must include the active environment variables (PATH etc)
        self.full_env = {**os.environ, **self.env}
        
    @asynccontextmanager
    async def get_session(self):
        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.full_env
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session
                
    def to_openai_tool(self, tool: Tool) -> Dict[str, Any]:
        """Convert an MCP Tool schema to an OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema
            }
        }
