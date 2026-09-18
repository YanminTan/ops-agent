"""
LangGraph Runtime - 诊断执行引擎 (三层路由版)

核心职责:
1. 意图分类 (triage): 小模型/规则将告警路由到 SOP / Skill / MCP
2. 管理诊断 thread 生命周期
3. 通过 SQLite checkpointer 持久化状态
4. 支持 interrupt/resume (人工审批闸门)
5. 支持时间旅行回放
6. 三路 (SOP / Skill / MCP) 统一回放
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from schemas.sop_schema import SOPDef
from compiler.sop_compiler import SOPCompiler
from mcp_tools.tools import TOOLS_REGISTRY
from triage.intent_classifier import IntentClassifier, IntentType, TriageResult
from triage.skill_executor import SkillExecutor, BUILTIN_SKILLS
from triage.mcp_direct_caller import MCPDirectCaller


class DiagnosisRuntime:
    """
    诊断执行引擎 (三层路由)

    架构:
        alarm ──▶ triage (意图分类)
                    ├── SOP yaml (多步编排, LangGraph StateGraph)
                    ├── Skill (轻量动作, 单函数执行)
                    └── MCP 直调 (一次调用)

    每个诊断任务是一个 thread，拥有独立的执行状态。
    所有状态变更通过 SQLite checkpointer 持久化。
    三路执行结果统一存储，支持统一回放。
    """

    def __init__(self, db_path: str = "diagnosis.db"):
        self.db_path = db_path
        self.compiler = SOPCompiler(tools_registry=TOOLS_REGISTRY)
        self.checkpointer: AsyncSqliteSaver | None = None
        self._conn = None

        # 编译后的 SOP graphs
        self.compiled_graphs: dict[str, Any] = {}
        # SOP 定义 (用于 triage 匹配)
        self.sop_defs: dict[str, SOPDef] = {}

        # Skill 执行器
        self.skill_executor = SkillExecutor()

        # MCP 直调执行器
        self.mcp_caller = MCPDirectCaller(tools_registry=TOOLS_REGISTRY)

        # 意图分类器 (启动后初始化)
        self.triage: IntentClassifier | None = None

        # Thread 元数据
        self.threads: dict[str, dict] = {}

    async def initialize(self):
        """初始化 runtime，创建 checkpointer 和 triage"""
        self._conn = await aiosqlite.connect(self.db_path)
        self.checkpointer = AsyncSqliteSaver(self._conn)

        # 初始化意图分类器
        sop_registry = {
            sop_id: {
                "name": sop.name,
                "description": sop.description,
                "trigger": {
                    "alert_rule": sop.trigger.get("alert_rule", "") if isinstance(sop.trigger, dict) else "",
                },
            }
            for sop_id, sop in self.sop_defs.items()
        }
        skill_registry = {
            sid: {
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
            }
            for sid, s in BUILTIN_SKILLS.items()
        }
        mcp_tools = {
            name: {"description": getattr(fn, "__doc__", "") or "", "keywords": []}
            for name, fn in TOOLS_REGISTRY.items()
        }
        self.triage = IntentClassifier(
            sop_registry=sop_registry,
            skill_registry=skill_registry,
            mcp_tools=mcp_tools,
        )

    async def close(self):
        """关闭 runtime"""
        if self._conn:
            await self._conn.close()

    # ─────────────────────────────────────────────
    # SOP 管理
    # ─────────────────────────────────────────────

    async def load_sop(self, sop: SOPDef) -> str:
        """加载并编译 SOP，返回 sop_id"""
        compiled = self.compiler.compile(sop)
        self.compiled_graphs[sop.sop_id] = compiled
        self.sop_defs[sop.sop_id] = sop
        return sop.sop_id

    async def load_sop_from_yaml(self, yaml_content: str) -> str:
        """从 YAML 加载 SOP"""
        sop = SOPDef.from_yaml(yaml_content)
        return await self.load_sop(sop)

    async def load_sop_from_file(self, path: str) -> str:
        """从文件加载 SOP"""
        sop = SOPDef.from_yaml_file(path)
        return await self.load_sop(sop)

    # ─────────────────────────────────────────────
    # 意图分类 (Triage)
    # ─────────────────────────────────────────────

    async def triage_alert(self, alert_context: dict[str, Any]) -> TriageResult:
        """
        对告警进行意图分类

        Returns:
            TriageResult: 分类结果 (intent, target_id, confidence)
        """
        if not self.triage:
            raise RuntimeError("Runtime not initialized")
        return self.triage.classify(alert_context)

    # ─────────────────────────────────────────────
    # 统一诊断入口 (三层路由)
    # ─────────────────────────────────────────────

    async def start_diagnosis(
        self,
        sop_id: str | None = None,
        alert_context: dict[str, Any] | None = None,
        route: str | None = None,
    ) -> dict[str, Any]:
        """
        统一诊断入口

        两种调用方式:
        1. 直接指定 sop_id (跳过 triage)
        2. 提供 alert_context，自动 triage 后路由

        Args:
            sop_id: 直接指定 SOP ID (可选)
            alert_context: 告警上下文 (可选，用于 triage)
            route: 强制路由到 sop/skill/mcp (可选，用于测试)

        Returns:
            thread_id, status, route_type, execution_log 等
        """
        thread_id = str(uuid.uuid4())

        # ── 确定路由 ──
        if route and sop_id:
            # 强制路由
            route_type = route
            target_id = sop_id
            triage_result = TriageResult(
                intent=IntentType(route),
                confidence=1.0,
                target_id=sop_id,
                reason="forced route",
            )
        elif sop_id:
            # 直接指定 SOP
            route_type = "sop"
            target_id = sop_id
            triage_result = TriageResult(
                intent=IntentType.SOP,
                confidence=1.0,
                target_id=sop_id,
                reason="direct sop_id",
            )
        elif alert_context:
            # 自动 triage
            triage_result = await self.triage_alert(alert_context)
            route_type = triage_result.intent.value
            target_id = triage_result.target_id
        else:
            raise ValueError("Either sop_id or alert_context must be provided")

        # ── 根据路由执行 ──
        try:
            if route_type == "sop":
                result = await self._execute_sop(thread_id, target_id, alert_context or {})
            elif route_type == "skill":
                result = await self._execute_skill(thread_id, target_id, alert_context or {})
            elif route_type == "mcp":
                result = await self._execute_mcp(thread_id, target_id, alert_context or {})
            else:
                result = {
                    "status": "error",
                    "error": f"Unknown route type: {route_type}",
                    "execution_log": [],
                }

            # 保存 thread 元数据
            self.threads[thread_id] = {
                "thread_id": thread_id,
                "route_type": route_type,
                "target_id": target_id,
                "triage": triage_result.to_dict(),
                "alert_context": alert_context or {},
                "status": result.get("status", "completed"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            return {
                "thread_id": thread_id,
                "route_type": route_type,
                "target_id": target_id,
                "triage": triage_result.to_dict(),
                "status": result.get("status", "completed"),
                "execution_log": result.get("execution_log", []),
                "report": result.get("final_report", result.get("result", "")),
                "error": result.get("error"),
            }

        except Exception as e:
            self.threads[thread_id] = {
                "thread_id": thread_id,
                "route_type": route_type,
                "target_id": target_id,
                "triage": triage_result.to_dict(),
                "alert_context": alert_context or {},
                "status": "error",
                "error": str(e),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            raise

    # ─────────────────────────────────────────────
    # SOP 执行路径
    # ─────────────────────────────────────────────

    async def _execute_sop(
        self,
        thread_id: str,
        sop_id: str,
        alert_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 SOP 路径 (LangGraph StateGraph)"""
        if sop_id not in self.compiled_graphs:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        config = {"configurable": {"thread_id": thread_id}}

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
            "execution_log": [
                {
                    "step": "triage",
                    "route": "sop",
                    "target": sop_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "iteration": 0,
        }

        graph = self.compiled_graphs[sop_id]
        result = await graph.ainvoke(initial_state, config)

        return {
            "status": "waiting_approval" if result.get("pending_interrupt") else "completed",
            "execution_log": result.get("execution_log", []),
            "final_report": result.get("final_report", ""),
            "pending_interrupt": result.get("pending_interrupt"),
            "error": result.get("error"),
        }

    # ─────────────────────────────────────────────
    # Skill 执行路径
    # ─────────────────────────────────────────────

    async def _execute_skill(
        self,
        thread_id: str,
        skill_id: str,
        alert_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 Skill 路径 (轻量动作)"""
        result = await self.skill_executor.execute(skill_id, alert_context)

        return {
            "status": result.get("status", "completed"),
            "execution_log": result.get("execution_log", []),
            "result": {k: v for k, v in result.items() if k != "execution_log"},
            "error": result.get("error"),
        }

    # ─────────────────────────────────────────────
    # MCP 直调路径
    # ────────────────────────────────────────────

    async def _execute_mcp(
        self,
        thread_id: str,
        tool_name: str,
        alert_context: dict[str, Any],
    ) -> dict[str, Any]:
        """执行 MCP 直调路径 (单点调用)"""
        result = await self.mcp_caller.execute(tool_name, {"context": alert_context})

        return {
            "status": result.get("status", "completed"),
            "execution_log": result.get("execution_log", []),
            "result": result.get("result", {}),
            "error": result.get("error"),
        }

    # ─────────────────────────────────────────────
    # 审批 (仅 SOP 路径需要)
    # ─────────────────────────────────────────────

    async def approve_interrupt(
        self,
        thread_id: str,
        approved: bool,
        comment: str = "",
    ) -> dict[str, Any]:
        """审批 interrupt (人工闸门)，仅 SOP 路径"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        if thread_meta["route_type"] != "sop":
            raise ValueError(f"Thread '{thread_id}' is not SOP route, cannot approve")

        sop_id = thread_meta["target_id"]
        if sop_id not in self.compiled_graphs:
            raise ValueError(f"SOP '{sop_id}' not loaded")

        config = {"configurable": {"thread_id": thread_id}}
        graph = self.compiled_graphs[sop_id]
        current_state = await graph.aget_state(config)

        if not current_state or not current_state.values.get("pending_interrupt"):
            raise ValueError(f"Thread '{thread_id}' has no pending interrupt")

        if approved:
            resume_input = {
                "pending_interrupt": None,
                "execution_log": current_state.values.get("execution_log", []) + [
                    {
                        "step": "interrupt_approved",
                        "approved": True,
                        "comment": comment,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }
            result = await graph.ainvoke(resume_input, config)

            self.threads[thread_id]["status"] = (
                "completed" if not result.get("pending_interrupt") else "waiting_approval"
            )
            self.threads[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

            return {
                "thread_id": thread_id,
                "status": self.threads[thread_id]["status"],
                "execution_log": result.get("execution_log", []),
                "final_report": result.get("final_report", ""),
                "pending_interrupt": result.get("pending_interrupt"),
            }
        else:
            self.threads[thread_id]["status"] = "rejected"
            self.threads[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            return {
                "thread_id": thread_id,
                "status": "rejected",
                "message": "Diagnosis terminated by user",
            }

    # ─────────────────────────────────────────────
    # 统一回放 (三路)
    # ─────────────────────────────────────────────

    async def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """获取 thread 当前状态 (三路统一)"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        route_type = thread_meta["route_type"]

        if route_type == "sop":
            sop_id = thread_meta["target_id"]
            config = {"configurable": {"thread_id": thread_id}}
            graph = self.compiled_graphs.get(sop_id)
            if graph:
                state = await graph.aget_state(config)
                return {**thread_meta, "state": state.values if state else {}}

        return thread_meta

    async def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """
        获取 thread 完整执行历史 (三路统一回放)

        SOP 路径: 从 LangGraph checkpointer 获取快照
        Skill/MCP 路径: 从 thread 元数据中的 execution_log 回放
        """
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        route_type = thread_meta["route_type"]

        if route_type == "sop":
            sop_id = thread_meta["target_id"]
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
            history.sort(key=lambda x: x.get("timestamp", ""))
            return history

        else:
            # Skill / MCP 路径: 从 execution_log 构建回放时间线
            return [
                {
                    "checkpoint_id": f"step_{i}",
                    "timestamp": entry.get("timestamp", ""),
                    "values": entry,
                    "next": [],
                }
                for i, entry in enumerate(thread_meta.get("execution_log", []))
            ]

    async def replay_to_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> dict[str, Any]:
        """时间旅行: 回放到指定 checkpoint (三路统一)"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")

        thread_meta = self.threads[thread_id]
        route_type = thread_meta["route_type"]

        if route_type == "sop":
            sop_id = thread_meta["target_id"]
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
                "route_type": route_type,
                "state": state.values if state else {},
            }
        else:
            # Skill / MCP: 回放 execution_log 到指定 step
            log = thread_meta.get("execution_log", [])
            step_idx = int(checkpoint_id.replace("step_", "")) if checkpoint_id.startswith("step_") else 0
            replayed = log[:step_idx + 1] if step_idx < len(log) else log
            return {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
                "route_type": route_type,
                "replayed_steps": replayed,
            }

    # ─────────────────────────────────────────────
    # Thread 管理
    # ─────────────────────────────────────────────

    async def list_threads(self) -> list[dict[str, Any]]:
        """列出所有诊断 thread"""
        return list(self.threads.values())

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        """获取单个 thread 详情"""
        if thread_id not in self.threads:
            raise ValueError(f"Thread '{thread_id}' not found")
        return self.threads[thread_id]
