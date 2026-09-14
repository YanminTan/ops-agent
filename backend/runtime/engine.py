"""
诊断运行时引擎

基于 LangGraph 的 StateGraph 执行诊断流程，
支持:
- SQLite checkpointer 持久化
- interrupt/resume 人工审批
- 时间旅行回放
- 执行日志记录
"""

from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from compiler.sop_compiler import SOPCompiler, DiagnosisState
from schemas.sop_schema import SOPDef
from mcp_tools.tools import TOOLS_REGISTRY


class DiagnosisRuntime:
    """
    诊断运行时引擎

    职责:
    1. 管理编译后的 StateGraph
    2. 提供 thread 级执行上下文
    3. 持久化状态到 SQLite
    4. 支持 interrupt/resume (人工审批)
    5. 支持时间旅行回放
    """

    def __init__(self, db_path: str = "diagnosis.db"):
        self.db_path = db_path
        self.compiler = SOPCompiler(tools_registry=TOOLS_REGISTRY)
        self.compiled_sops: dict[str, Any] = {}  # sop_id -> compiled graph
        self.sop_defs: dict[str, SOPDef] = {}    # sop_id -> SOPDef
        self.checkpointer: AsyncSqliteSaver | None = None

    async def initialize(self):
        """初始化运行时，创建 checkpointer"""
        self.checkpointer = AsyncSqliteSaver.from_conn_string(self.db_path)
        await self.checkpointer.setup()

    async def load_sop(self, sop: SOPDef) -> str:
        """加载并编译 SOP"""
        compiled = self.compiler.compile(sop)
        self.compiled_sops[sop.sop_id] = compiled
        self.sop_defs[sop.sop_id] = sop
        return sop.sop_id

    async def load_sop_from_yaml(self, yaml_content: str) -> str:
        """从 YAML 加载 SOP"""
        sop = SOPDef.from_yaml(yaml_content)
        return await self.load_sop(sop)

    async def start_diagnosis(
        self,
        sop_id: str,
        alert_context: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """
        启动诊断流程

        Args:
            sop_id: SOP 标识
            alert_context: 告警上下文
            thread_id: 可选的 thread ID，不传则自动生成

        Returns:
            执行结果，包含 thread_id, status, current_step 等
        """
        if sop_id not in self.compiled_sops:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        if not thread_id:
            thread_id = str(uuid.uuid4())

        graph = self.compiled_sops[sop_id]

        # 初始状态
        initial_state = {
            "messages": [],
            "sop_id": sop_id,
            "alert_context": alert_context,
            "collected_facts": {},
            "current_step": "",
            "step_results": {},
            "report_sections": {},
            "final_report": "",
            "pending_interrupt": None,
            "error": None,
            "execution_log": [],
            "iteration": 0,
        }

        # 配置
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        # 执行
        try:
            result = await graph.ainvoke(
                initial_state,
                config=config,
            )

            # 检查是否有 interrupt
            pending_interrupt = result.get("pending_interrupt")
            status = "waiting_approval" if pending_interrupt else "completed"

            return {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "status": status,
                "current_step": result.get("current_step", ""),
                "collected_facts": result.get("collected_facts", {}),
                "step_results": result.get("step_results", {}),
                "report_sections": result.get("report_sections", {}),
                "final_report": result.get("final_report", ""),
                "pending_interrupt": pending_interrupt,
                "execution_log": result.get("execution_log", []),
                "error": result.get("error"),
            }

        except Exception as e:
            return {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "status": "error",
                "error": str(e),
                "execution_log": [],
            }

    async def approve_interrupt(
        self,
        thread_id: str,
        approved: bool = True,
        comment: str = "",
    ) -> dict[str, Any]:
        """
        审批 interrupt（人工闸门）

        Args:
            thread_id: thread ID
            approved: 是否批准
            comment: 审批意见

        Returns:
            更新后的执行结果
        """
        config = {"configurable": {"thread_id": thread_id}}

        # 获取当前状态
        current_state = await self.get_thread_state(thread_id)
        if not current_state:
            raise ValueError(f"Thread '{thread_id}' not found")

        sop_id = current_state.get("sop_id")
        if not sop_id:
            raise ValueError(f"Thread '{thread_id}' has no sop_id")

        graph = self.compiled_sops.get(sop_id)
        if not graph:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        # 更新状态，清除 pending_interrupt
        updated_state = {
            **current_state,
            "pending_interrupt": None,
        }

        # 记录审批日志
        approval_log = {
            "step_id": current_state.get("current_step", ""),
            "type": "approval",
            "approved": approved,
            "comment": comment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        updated_state["execution_log"] = current_state.get("execution_log", []) + [approval_log]

        if not approved:
            updated_state["status"] = "rejected"
            updated_state["error"] = f"Approval rejected: {comment}"
            return updated_state

        # 继续执行
        try:
            result = await graph.ainvoke(
                updated_state,
                config=config,
            )

            pending_interrupt = result.get("pending_interrupt")
            status = "waiting_approval" if pending_interrupt else "completed"

            return {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "status": status,
                "current_step": result.get("current_step", ""),
                "collected_facts": result.get("collected_facts", {}),
                "step_results": result.get("step_results", {}),
                "report_sections": result.get("report_sections", {}),
                "final_report": result.get("final_report", ""),
                "pending_interrupt": pending_interrupt,
                "execution_log": result.get("execution_log", []),
                "error": result.get("error"),
            }

        except Exception as e:
            return {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "status": "error",
                "error": str(e),
            }

    async def get_thread_state(self, thread_id: str) -> dict[str, Any] | None:
        """获取 thread 当前状态"""
        if not self.checkpointer:
            raise RuntimeError("Runtime not initialized")

        # 从 checkpointer 获取状态
        # 这里需要知道 sop_id 来获取正确的 graph
        # 简化处理：遍历所有已加载的 SOP
        for sop_id, graph in self.compiled_sops.items():
            config = {"configurable": {"thread_id": thread_id}}
            try:
                state = await graph.aget(config)
                if state:
                    return state
            except Exception:
                continue

        return None

    async def get_thread_history(
        self,
        thread_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取 thread 执行历史（时间旅行）

        Args:
            thread_id: thread ID
            limit: 最大返回条数

        Returns:
            状态历史列表，按时间倒序
        """
        if not self.checkpointer:
            raise RuntimeError("Runtime not initialized")

        history = []

        for sop_id, graph in self.compiled_sops.items():
            config = {"configurable": {"thread_id": thread_id}}
            try:
                async for state in graph.astream(config):
                    history.append({
                        "checkpoint": state.get("config", {}),
                        "state": state.get("state", {}),
                        "timestamp": state.get("timestamp", ""),
                    })
                    if len(history) >= limit:
                        break
            except Exception:
                continue

        # 按时间倒序
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return history[:limit]

    async def replay_from_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """
        从指定 checkpoint 回放

        Args:
            thread_id: thread ID
            checkpoint_id: checkpoint ID

        Returns:
            回放结果
        """
        # TODO: 实现从特定 checkpoint 回放
        # 需要 langgraph 的 update_state API
        raise NotImplementedError("Checkpoint replay not yet implemented")

    async def list_threads(self, limit: int = 50) -> list[dict[str, Any]]:
        """列出所有 threads"""
        # TODO: 从 checkpointer 查询所有 threads
        return []

    async def close(self):
        """关闭运行时"""
        if self.checkpointer:
            await self.checkpointer.close()
