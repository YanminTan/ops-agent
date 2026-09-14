"""
LangGraph Runtime - 诊断执行引擎

核心职责:
1. 管理诊断 thread 生命周期
2. 通过 SQLite checkpointer 持久化状态
3. 支持 interrupt/resume (人工审批闸门)
4. 支持时间旅行回放
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from schemas.sop_schema import SOPDef
from compiler.sop_compiler import SOPCompiler
from mcp_tools.tools import TOOLS_REGISTRY


class DiagnosisRuntime:
    """
    诊断执行引擎

    每个诊断任务是一个 thread，拥有独立的执行状态。
    所有状态变更通过 SQLite checkpointer 持久化。
    """

    def __init__(self, db_path: str = "diagnosis.db"):
        self.db_path = db_path
        self.compiler = SOPCompiler(tools_registry=TOOLS_REGISTRY)
        self.checkpointer: AsyncSqliteSaver | None = None
        self.compiled_graphs: dict[str, Any] = {}
        self.threads: dict[str, dict] = {}

    async def initialize(self):
        """初始化 runtime，创建 checkpointer"""
        self.checkpointer = await AsyncSqliteSaver.from_conn_string(self.db_path)

    async def close(self):
        """关闭 runtime"""
        if self.checkpointer:
            await self.checkpointer.close()

    async def load_sop(self, sop: SOPDef) -> str:
        """加载并编译 SOP，返回 sop_id"""
        compiled = self.compiler.compile(sop)
        self.compiled_graphs[sop.sop_id] = compiled
        return sop.sop_id

    async def load_sop_from_yaml(self, yaml_content: str) -> str:
        """从 YAML 加载 SOP"""
        sop = SOPDef.from_yaml(yaml_content)
        return await self.load_sop(sop)

    async def load_sop_from_file(self, path: str) -> str:
        """从文件加载 SOP"""
        sop = SOPDef.from_yaml_file(path)
        return await self.load_sop(sop)

    async def start_diagnosis(
        self,
        sop_id: str,
        alert_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        启动诊断 thread

        Returns:
            thread_id: 诊断线程ID
            status: 运行状态
            current_step: 当前步骤
        """
        if sop_id not in self.compiled_graphs:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

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

        # 执行 graph
        graph = self.compiled_graphs[sop_id]

        try:
            result = await graph.ainvoke(initial_state, config)

            # 保存 thread 元数据
            self.threads[thread_id] = {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "alert_context": alert_context,
                "status": "completed" if not result.get("pending_interrupt") else "waiting_approval",
                "current_step": result.get("current_step", ""),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            return {
                "thread_id": thread_id,
                "status": self.threads[thread_id]["status"],
                "current_step": result.get("current_step", ""),
                "execution_log": result.get("execution_log", []),
                "report_sections": result.get("report_sections", {}),
                "final_report": result.get("final_report", ""),
                "pending_interrupt": result.get("pending_interrupt"),
                "error": result.get("error"),
            }

        except Exception as e:
            self.threads[thread_id] = {
                "thread_id": thread_id,
                "sop_id": sop_id,
                "alert_context": alert_context,
                "status": "error",
                "error": str(e),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            raise

    async def approve_interrupt(
        self,
        thread_id: str,
        approved: bool,
        comment: str = "",
    ) -> dict[str, Any]:
        """
        审批 interrupt (人工闸门)

        Args:
            thread_id: 诊断线程ID
            approved: 是否批准
            comment: 审批意见

        Returns:
            更新后的 thread 状态
        """
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        sop_id = thread_meta["sop_id"]

        if sop_id not in self.compiled_graphs:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        config = {"configurable": {"thread_id": thread_id}}

        # 获取当前状态
        graph = self.compiled_graphs[sop_id]
        current_state = await graph.aget_state(config)

        if not current_state or not current_state.values.get("pending_interrupt"):
            raise ValueError(f"Thread '{thread_id}' has no pending interrupt")

        # 构造恢复输入
        if approved:
            resume_input = {
                "pending_interrupt": None,
                "execution_log": current_state.values.get("execution_log", []) + [
                    {
                        "type": "interrupt_approved",
                        "approved": True,
                        "comment": comment,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
        else:
            # 拒绝则终止
            return {
                "thread_id": thread_id,
                "status": "rejected",
                "message": "Diagnosis terminated by user",
            }

        # 继续执行
        result = await graph.ainvoke(resume_input, config)

        # 更新 thread 元数据
        self.threads[thread_id]["status"] = "completed" if not result.get("pending_interrupt") else "waiting_approval"
        self.threads[thread_id]["current_step"] = result.get("current_step", "")
        self.threads[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

        return {
            "thread_id": thread_id,
            "status": self.threads[thread_id]["status"],
            "current_step": result.get("current_step", ""),
            "execution_log": result.get("execution_log", []),
            "report_sections": result.get("report_sections", {}),
            "final_report": result.get("final_report", ""),
            "pending_interrupt": result.get("pending_interrupt"),
        }

    async def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """获取 thread 当前状态"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        sop_id = thread_meta["sop_id"]
        config = {"configurable": {"thread_id": thread_id}}

        graph = self.compiled_graphs.get(sop_id)
        if not graph:
            return thread_meta

        state = await graph.aget_state(config)

        return {
            **thread_meta,
            "state": state.values if state else {},
        }

    async def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """
        获取 thread 完整执行历史 (时间旅行回放)

        Returns:
            按时间排序的状态快照列表
        """
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        sop_id = thread_meta["sop_id"]
        config = {"configurable": {"thread_id": thread_id}}

        graph = self.compiled_graphs.get(sop_id)
        if not graph:
            return []

        history = []
        async for snapshot in graph.aget_state_history(config):
            history.append({
                "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id"),
                "timestamp": snapshot.created_at,
                "values": snapshot.values,
                "next": snapshot.next,
            })

        # 按时间排序
        history.sort(key=lambda x: x.get("timestamp", ""))
        return history

    async def replay_to_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """
        时间旅行: 回放到指定 checkpoint

        Args:
            thread_id: 诊断线程ID
            checkpoint_id: 目标 checkpoint

        Returns:
            该 checkpoint 的状态
        """
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        sop_id = thread_meta["sop_id"]
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        graph = self.compiled_graphs.get(sop_id)
        if not graph:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        state = await graph.aget_state(config)

        return {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
            "state": state.values if state else {},
        }

    async def list_threads(self) -> list[dict[str, Any]]:
        """列出所有诊断 thread"""
        return list(self.threads.values())

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        """获取单个 thread 详情"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")
        return self.threads[thread_id]
