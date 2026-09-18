"""
MCP 直调执行器

单点 MCP 工具直接调用，不走 SOP 编排也不走 Skill。
适用于简单的一次性查询操作。
"""

from __future__ import annotations

import json
from typing import Any, Callable
from datetime import datetime, timezone


class MCPDirectCaller:
    """MCP 工具直调执行器"""

    def __init__(self, tools_registry: dict[str, Callable] | None = None):
        self.tools_registry = tools_registry or {}

    def list_tools(self) -> list[dict[str, Any]]:
        """列出所有可用 MCP 工具"""
        return [
            {
                "tool_name": name,
                "description": getattr(fn, "__doc__", "") or "",
            }
            for name, fn in self.tools_registry.items()
        ]

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        直接调用 MCP 工具

        Returns:
            执行结果，包含 execution_log 用于回放
        """
        execution_log = [
            {
                "step": "mcp_call_start",
                "tool_name": tool_name,
                "args": args or {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

        if tool_name not in self.tools_registry:
            execution_log.append({
                "step": "mcp_call_error",
                "error": f"Tool '{tool_name}' not found in registry",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {
                "tool_name": tool_name,
                "status": "error",
                "error": f"Tool '{tool_name}' not found",
                "execution_log": execution_log,
            }

        try:
            tool_fn = self.tools_registry[tool_name]
            result = await tool_fn(**(args or {})) if callable(tool_fn) else {"result": tool_fn}

            execution_log.append({
                "step": "mcp_call_complete",
                "tool_name": tool_name,
                "result_summary": str(result)[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            return {
                "tool_name": tool_name,
                "status": "completed",
                "result": result,
                "execution_log": execution_log,
            }
        except Exception as e:
            execution_log.append({
                "step": "mcp_call_error",
                "tool_name": tool_name,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {
                "tool_name": tool_name,
                "status": "error",
                "error": str(e),
                "execution_log": execution_log,
            }
