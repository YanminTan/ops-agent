"""
意图分类器 (Triage)

使用小模型进行意图分类，将告警路由到:
- SOP: 多步编排 (命中已知 SOP)
- Skill: 轻量动作 (命中 Skill)
- MCP: 单点直调 (直接调用 MCP 工具)
"""

from __future__ import annotations

import json
from typing import Any
from enum import Enum


class IntentType(str, Enum):
    """意图类型"""
    SOP = "sop"
    SKILL = "skill"
    MCP = "mcp"
    UNKNOWN = "unknown"


class TriageResult:
    """分类结果"""
    def __init__(
        self,
        intent: IntentType,
        confidence: float,
        target_id: str,
        reason: str = "",
    ):
        self.intent = intent
        self.confidence = confidence
        self.target_id = target_id  # sop_id / skill_id / tool_name
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "target_id": self.target_id,
            "reason": self.reason,
        }


class IntentClassifier:
    """
    意图分类器

    基于规则 + 关键词匹配进行简单分类
    后续可替换为小模型 (如 Qwen-1.5B / Phi-3-mini)
    """

    def __init__(
        self,
        sop_registry: dict[str, dict[str, Any]] | None = None,
        skill_registry: dict[str, dict[str, Any]] | None = None,
        mcp_tools: dict[str, Any] | None = None,
    ):
        self.sop_registry = sop_registry or {}
        self.skill_registry = skill_registry or {}
        self.mcp_tools = mcp_tools or {}

    def classify(
        self,
        alert_context: dict[str, Any],
    ) -> TriageResult:
        """
        对告警进行意图分类

        Args:
            alert_context: 告警上下文

        Returns:
            TriageResult: 分类结果
        """
        alert_message = alert_context.get("message", "")
        alert_source = alert_context.get("source", "")
        alert_level = alert_context.get("level", "")
        service = alert_context.get("service", "")

        # 1. 尝试匹配 SOP
        sop_match = self._match_sop(alert_context)
        if sop_match:
            return TriageResult(
                intent=IntentType.SOP,
                confidence=0.9,
                target_id=sop_match,
                reason=f"匹配到 SOP: {sop_match}",
            )

        # 2. 尝试匹配 Skill
        skill_match = self._match_skill(alert_context)
        if skill_match:
            return TriageResult(
                intent=IntentType.SKILL,
                confidence=0.8,
                target_id=skill_match,
                reason=f"匹配到 Skill: {skill_match}",
            )

        # 3. 尝试匹配 MCP 工具
        mcp_match = self._match_mcp(alert_context)
        if mcp_match:
            return TriageResult(
                intent=IntentType.MCP,
                confidence=0.7,
                target_id=mcp_match,
                reason=f"匹配到 MCP 工具: {mcp_match}",
            )

        # 4. 未知意图
        return TriageResult(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            target_id="",
            reason="未匹配到任何 SOP/Skill/MCP",
        )

    def _match_sop(self, alert_context: dict[str, Any]) -> str | None:
        """匹配 SOP"""
        alert_message = alert_context.get("message", "").lower()
        service = alert_context.get("service", "").lower()

        for sop_id, sop_info in self.sop_registry.items():
            sop_name = sop_info.get("name", "").lower()
            sop_desc = sop_info.get("description", "").lower()
            trigger_rule = sop_info.get("trigger", {}).get("alert_rule", "").lower()

            # 关键词匹配
            if service and service in sop_name:
                return sop_id
            if trigger_rule and trigger_rule in alert_message:
                return sop_id
            if sop_name and sop_name in alert_message:
                return sop_id
            # 中文描述匹配
            if sop_desc and any(kw in alert_message for kw in sop_desc.split()):
                return sop_id

        return None

    def _match_skill(self, alert_context: dict[str, Any]) -> str | None:
        """匹配 Skill"""
        alert_message = alert_context.get("message", "").lower()
        service = alert_context.get("service", "").lower()

        for skill_id, skill_info in self.skill_registry.items():
            skill_name = skill_info.get("name", "").lower()
            skill_desc = skill_info.get("description", "").lower()
            keywords = skill_info.get("keywords", [])

            # 关键词匹配
            if service and service in skill_name:
                return skill_id
            for keyword in keywords:
                if keyword.lower() in alert_message:
                    return skill_id
            if skill_name and skill_name in alert_message:
                return skill_id

        return None

    def _match_mcp(self, alert_context: dict[str, Any]) -> str | None:
        """匹配 MCP 工具"""
        alert_message = alert_context.get("message", "").lower()

        for tool_name, tool_info in self.mcp_tools.items():
            tool_desc = tool_info.get("description", "").lower()
            keywords = tool_info.get("keywords", [])

            # 关键词匹配
            for keyword in keywords:
                if keyword.lower() in alert_message:
                    return tool_name
            if tool_desc and tool_desc in alert_message:
                return tool_name

        return None
