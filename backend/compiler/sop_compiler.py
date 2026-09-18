"""
SOP Compiler: YAML → LangGraph StateGraph

将声明式 SOP YAML 编译为确定性的 StateGraph，
支持 tool_call / llm_analysis / branch / interrupt / parallel / loop 等步骤类型。
"""

from __future__ import annotations

import json
import operator
from typing import Any, Annotated, Literal, TypedDict
from dataclasses import dataclass, field

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from schemas.sop_schema import SOPDef, StepDef, StepType, REPORT_SECTIONS


# ─────────────────────────────────────────────
# State 定义 (TypedDict)
# ─────────────────────────────────────────────

class DiagnosisState(TypedDict):
    """诊断流程的全局状态"""
    messages: Annotated[list, add_messages]
    sop_id: str
    alert_context: dict[str, Any]
    collected_facts: dict[str, Any]
    current_step: str
    step_results: dict[str, Any]
    report_sections: dict[str, str]
    final_report: str
    pending_interrupt: dict[str, Any] | None
    error: str | None
    execution_log: list[dict[str, Any]]
    iteration: int


# ────────────────────────────────────────────
# Compiler
# ─────────────────────────────────────────────

class SOPCompiler:
    """
    将 SOP YAML 编译为 LangGraph StateGraph

    核心逻辑:
    1. 解析 YAML 为 SOPDef
    2. 为每个 Step 创建对应的 node function
    3. 根据 step.next / step.condition 建立 edges
    4. interrupt 步骤使用 langgraph 的 interrupt() 原语
    5. 返回编译后的 StateGraph
    """

    def __init__(self, tools_registry: dict[str, callable] | None = None):
        self.tools_registry = tools_registry or {}

    def compile(self, sop: SOPDef) -> StateGraph:
        """编译 SOP 为 StateGraph"""
        builder = StateGraph(DiagnosisState)

        # 构建步骤索引
        step_map: dict[str, StepDef] = {s.id: s for s in sop.steps}

        # 为每个步骤创建 node
        for step in sop.steps:
            node_fn = self._build_node(step, step_map, sop)
            builder.add_node(step.id, node_fn)

        # 建立 edges
        entry_step = sop.steps[0] if sop.steps else None
        if entry_step:
            builder.add_edge(START, entry_step.id)

        for step in sop.steps:
            self._build_edges(builder, step, step_map)

        return builder.compile()

    def _build_node(self, step: StepDef, step_map: dict, sop: SOPDef) -> callable:
        """为单个步骤构建 node function"""

        if step.type == StepType.TOOL_CALL:
            return self._build_tool_node(step)
        elif step.type == StepType.LLM_ANALYSIS:
            return self._build_llm_node(step, sop)
        elif step.type == StepType.BRANCH:
            return self._build_branch_node(step, step_map)
        elif step.type == StepType.INTERRUPT:
            return self._build_interrupt_node(step)
        elif step.type == StepType.REPORT_SECTION:
            return self._build_report_node(step, sop)
        elif step.type == StepType.PARALLEL:
            return self._build_parallel_node(step, step_map)
        else:
            raise ValueError(f"Unknown step type: {step.type}")

    def _build_tool_node(self, step: StepDef) -> callable:
        """构建工具调用节点"""
        tool_name = step.tool
        tool_args_template = step.tool_args

        async def tool_node(state: DiagnosisState) -> dict:
            log_entry = {
                "step_id": step.id,
                "type": "tool_call",
                "tool": tool_name,
                "status": "running",
            }

            try:
                # 解析参数模板（支持从 state 中引用变量）
                resolved_args = self._resolve_template(tool_args_template, state)

                # 调用工具
                if tool_name in self.tools_registry:
                    tool_fn = self.tools_registry[tool_name]
                    result = await tool_fn(**resolved_args) if callable(tool_fn) else resolved_args
                else:
                    result = {"error": f"Tool '{tool_name}' not found in registry"}

                return {
                    "step_results": {**state.get("step_results", {}), step.id: result},
                    "collected_facts": {**state.get("collected_facts", {}), step.id: result},
                    "current_step": step.id,
                    "execution_log": state.get("execution_log", []) + [{**log_entry, "status": "success", "result": result}],
                }
            except Exception as e:
                return {
                    "current_step": step.id,
                    "error": str(e),
                    "execution_log": state.get("execution_log", []) + [{**log_entry, "status": "error", "error": str(e)}],
                }

        return tool_node

    def _build_llm_node(self, step: StepDef, sop: SOPDef) -> callable:
        """构建 LLM 分析节点"""
        prompt_template = step.prompt_template or step.prompt or ""

        async def llm_node(state: DiagnosisState) -> dict:
            log_entry = {
                "step_id": step.id,
                "type": "llm_analysis",
                "status": "running",
            }

            try:
                # 解析 prompt 模板
                resolved_prompt = self._resolve_template_str(prompt_template, state)

                # 这里预留 LLM 调用接口，实际运行时注入
                # 暂时返回结构化占位
                analysis_result = {
                    "prompt": resolved_prompt,
                    "analysis": f"[LLM Analysis for step: {step.id}]",
                    "facts_used": list(state.get("collected_facts", {}).keys()),
                }

                return {
                    "step_results": {**state.get("step_results", {}), step.id: analysis_result},
                    "messages": state.get("messages", []) + [AIMessage(content=resolved_prompt)],
                    "current_step": step.id,
                    "execution_log": state.get("execution_log", []) + [{**log_entry, "status": "success"}],
                }
            except Exception as e:
                return {
                    "current_step": step.id,
                    "error": str(e),
                    "execution_log": state.get("execution_log", []) + [{**log_entry, "status": "error", "error": str(e)}],
                }

        return llm_node

    def _build_branch_node(self, step: StepDef, step_map: dict) -> callable:
        """构建条件分支节点"""

        async def branch_node(state: DiagnosisState) -> dict:
            condition = step.condition or ""
            result = self._evaluate_condition(condition, state)

            return {
                "step_results": {**state.get("step_results", {}), step.id: {"branch_result": result}},
                "current_step": step.id,
                "execution_log": state.get("execution_log", []) + [
                    {"step_id": step.id, "type": "branch", "condition": condition, "result": result}
                ],
            }

        return branch_node

    def _build_interrupt_node(self, step: StepDef) -> callable:
        """构建人工审批 interrupt 节点（写路径闸门）"""

        async def interrupt_node(state: DiagnosisState) -> dict:
            # 设置 pending_interrupt，触发 langgraph interrupt
            interrupt_payload = {
                "step_id": step.id,
                "message": step.message or "需要人工审批",
                "context": {
                    "collected_facts": state.get("collected_facts", {}),
                    "step_results": state.get("step_results", {}),
                },
            }

            return {
                "pending_interrupt": interrupt_payload,
                "current_step": step.id,
                "execution_log": state.get("execution_log", []) + [
                    {"step_id": step.id, "type": "interrupt", "status": "waiting_approval"}
                ],
            }

        return interrupt_node

    def _build_report_node(self, step: StepDef, sop: SOPDef) -> callable:
        """构建报告段落生成节点"""
        section_key = step.section or "symptom"

        async def report_node(state: DiagnosisState) -> dict:
            # 从 collected_facts 和 step_results 生成报告段落
            section_content = self._generate_section_content(section_key, state, sop)

            report_sections = {**state.get("report_sections", {}), section_key: section_content}

            # 如果所有段落都已生成，组装最终报告
            final_report = ""
            if all(k in report_sections for k in REPORT_SECTIONS):
                final_report = self._assemble_report(report_sections, sop)

            return {
                "report_sections": report_sections,
                "final_report": final_report,
                "current_step": step.id,
                "execution_log": state.get("execution_log", []) + [
                    {"step_id": step.id, "type": "report_section", "section": section_key}
                ],
            }

        return report_node

    def _build_parallel_node(self, step: StepDef, step_map: dict) -> callable:
        """构建并行执行节点"""

        async def parallel_node(state: DiagnosisState) -> dict:
            # 并行步骤在编译时已经展开为独立节点
            # 这里只做聚合
            results = {}
            for sub_step_id in step.parallel_steps:
                if sub_step_id in state.get("step_results", {}):
                    results[sub_step_id] = state["step_results"][sub_step_id]

            return {
                "step_results": {**state.get("step_results", {}), step.id: results},
                "current_step": step.id,
                "execution_log": state.get("execution_log", []) + [
                    {"step_id": step.id, "type": "parallel", "sub_steps": step.parallel_steps}
                ],
            }

        return parallel_node

    def _build_edges(self, builder: StateGraph, step: StepDef, step_map: dict):
        """为步骤建立 edges"""

        if step.type == StepType.BRANCH:
            # 条件分支: 根据 branch_result 路由到不同节点
            def route_fn(state: DiagnosisState) -> str:
                branch_result = state.get("step_results", {}).get(step.id, {}).get("branch_result", "")
                for branch in step.branches:
                    if branch.get("value") == branch_result:
                        return branch.get("next", END)
                return step.next or END

            builder.add_conditional_edges(step.id, route_fn)
            return

        if step.type == StepType.INTERRUPT:
            # interrupt 后需要等待审批，审批通过后继续
            # 用条件边实现：如果有 pending_interrupt 则等待，否则继续
            def interrupt_route(state: DiagnosisState) -> str:
                if state.get("pending_interrupt") and state["pending_interrupt"].get("step_id") == step.id:
                    return "__interrupt__"
                return step.next or END

            builder.add_conditional_edges(step.id, interrupt_route)
            return

        # 普通步骤: 直接连到 next
        next_step = step.next
        if next_step and next_step in step_map:
            builder.add_edge(step.id, next_step)
        elif next_step == "__end__":
            builder.add_edge(step.id, END)
        else:
            # 没有 next，默认 END
            builder.add_edge(step.id, END)

    def _resolve_template(self, template: dict, state: dict) -> dict:
        """递归解析参数模板中的变量引用"""
        resolved = {}
        for k, v in template.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                ref = v[2:-1]
                resolved[k] = self._resolve_ref(ref, state)
            elif isinstance(v, dict):
                resolved[k] = self._resolve_template(v, state)
            else:
                resolved[k] = v
        return resolved

    def _resolve_template_str(self, template: str, state: dict) -> str:
        """解析字符串模板中的 ${var} 引用"""
        import re
        def replacer(match):
            ref = match.group(1)
            return str(self._resolve_ref(ref, state))
        return re.sub(r'\$\{([^}]+)\}', replacer, template)

    def _resolve_ref(self, ref: str, state: dict) -> Any:
        """解析 state 中的引用路径，如 alert_context.alert_id"""
        parts = ref.split(".")
        current = state
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return f"<unresolved:{ref}>"
        return current

    def _evaluate_condition(self, condition: str, state: dict) -> str:
        """简单条件评估"""
        # 支持简单的变量比较: ${var} == "value"
        import re
        match = re.match(r'\$\{([^}]+)\}\s*==\s*["\']?([^"\']+)["\']?', condition)
        if match:
            ref, expected = match.group(1), match.group(2)
            actual = self._resolve_ref(ref, state)
            return "true" if str(actual) == expected else "false"
        return "false"

    def _generate_section_content(self, section_key: str, state: dict, sop: SOPDef) -> str:
        """根据收集的事实生成报告段落内容"""
        section_name = REPORT_SECTIONS.get(section_key, section_key)
        facts = state.get("collected_facts", {})
        step_results = state.get("step_results", {})

        content_parts = [f"## {section_name}\n"]

        if section_key == "symptom":
            alert_ctx = state.get("alert_context", {})
            content_parts.append(f"- 告警来源: {alert_ctx.get('source', 'N/A')}")
            content_parts.append(f"- 告警级别: {alert_ctx.get('level', 'N/A')}")
            content_parts.append(f"- 告警内容: {alert_ctx.get('message', 'N/A')}")
            content_parts.append(f"- 首次触发: {alert_ctx.get('timestamp', 'N/A')}")

        elif section_key == "root_cause":
            content_parts.append("基于以下采集数据分析:\n")
            for step_id, result in step_results.items():
                content_parts.append(f"- **{step_id}**: {json.dumps(result, ensure_ascii=False, default=str)[:200]}")

        elif section_key == "impact_scope":
            content_parts.append("- 影响服务: 待分析")
            content_parts.append("- 影响用户: 待分析")
            content_parts.append("- 影响时长: 待分析")

        elif section_key == "remediation":
            content_parts.append("### 紧急处置\n- 待生成\n\n### 长期修复\n- 待生成")

        elif section_key == "postmortem":
            content_parts.append("### 改进项\n- 待生成\n\n### 行动项\n- 待生成")

        return "\n".join(content_parts)

    def _assemble_report(self, sections: dict[str, str], sop: SOPDef) -> str:
        """组装最终五段式报告"""
        report_parts = [
            f"# 运维诊断报告",
            f"**SOP**: {sop.name} (v{sop.version})",
            f"**生成时间**: {self._now_iso()}",
            "---\n",
        ]

        for key in ["symptom", "root_cause", "impact_scope", "remediation", "postmortem"]:
            if key in sections:
                report_parts.append(sections[key])
                report_parts.append("\n---\n")

        return "\n".join(report_parts)

    def _now_iso(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
