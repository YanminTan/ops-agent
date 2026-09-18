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

        匹配优先级:
        1. 精确匹配 SOP (alert_rule 完全匹配)
        2. 诊断场景检测 (包含诊断/故障/异常等关键词 → SOP)
        3. 精确匹配 Skill (关键词完全匹配)
        4. 精确匹配 MCP (工具关键词匹配)
        5. 模糊匹配 SOP (描述包含)
        6. 未知意图
        """
        alert_message = alert_context.get("message", "")
        alert_source = alert_context.get("source", "")
        alert_level = alert_context.get("level", "")
        service = alert_context.get("service", "")

        # 1. 精确匹配 SOP (alert_rule)
        exact_sop = self._exact_match_sop(alert_context)
        if exact_sop:
            return TriageResult(
                intent=IntentType.SOP,
                confidence=0.95,
                target_id=exact_sop,
                reason=f"精确匹配到 SOP: {exact_sop}",
            )

        # 2. 诊断场景检测 (优先于 MCP，避免"CPU过高"被匹配到 query_metrics)
        diagnosis_keywords = ["过高", "过低", "耗尽", "异常", "故障", "超时", "失败", "错误", "诊断", "排查"]
        if any(kw in alert_message for kw in diagnosis_keywords):
            fuzzy_sop = self._fuzzy_match_sop(alert_context)
            if fuzzy_sop:
                return TriageResult(
                    intent=IntentType.SOP,
                    confidence=0.8,
                    target_id=fuzzy_sop,
                    reason=f"诊断场景，匹配到 SOP: {fuzzy_sop}",
                )

        # 3. 精确匹配 Skill
        exact_skill = self._exact_match_skill(alert_context)
        if exact_skill:
            return TriageResult(
                intent=IntentType.SKILL,
                confidence=0.85,
                target_id=exact_skill,
                reason=f"精确匹配到 Skill: {exact_skill}",
            )

        # 4. 精确匹配 MCP
        exact_mcp = self._exact_match_mcp(alert_context)
        if exact_mcp:
            return TriageResult(
                intent=IntentType.MCP,
                confidence=0.75,
                target_id=exact_mcp,
                reason=f"精确匹配到 MCP 工具: {exact_mcp}",
            )

        # 5. 模糊匹配 SOP (描述包含)
        fuzzy_sop = self._fuzzy_match_sop(alert_context)
        if fuzzy_sop:
            return TriageResult(
                intent=IntentType.SOP,
                confidence=0.7,
                target_id=fuzzy_sop,
                reason=f"模糊匹配到 SOP: {fuzzy_sop}",
            )

        # 6. 未知意图
        return TriageResult(
            intent=IntentType.UNKNOWN,
            confidence=0.0,
            target_id="",
            reason="未匹配到任何 SOP/Skill/MCP",
        )

    def _exact_match_sop(self, alert_context: dict[str, Any]) -> str | None:
        """精确匹配 SOP - alert_rule 完全匹配"""
        alert_message = alert_context.get("message", "").lower()

        for sop_id, sop_info in self.sop_registry.items():
            trigger_rule = sop_info.get("trigger", {}).get("alert_rule", "").lower()
            # alert_rule 必须完全出现在 alert_message 中
            if trigger_rule and len(trigger_rule) > 3 and trigger_rule in alert_message:
                return sop_id

        return None

    def _exact_match_skill(self, alert_context: dict[str, Any]) -> str | None:
        """精确匹配 Skill - 关键词完全匹配"""
        alert_message = alert_context.get("message", "").lower()

        for skill_id, skill_info in self.skill_registry.items():
            keywords = skill_info.get("keywords", [])
            # 关键词必须完全匹配
            for keyword in keywords:
                if keyword and len(keyword) > 2 and keyword.lower() in alert_message:
                    return skill_id

        return None

    def _exact_match_mcp(self, alert_context: dict[str, Any]) -> str | None:
        """精确匹配 MCP - 工具关键词匹配"""
        alert_message = alert_context.get("message", "").lower()

        # MCP 工具关键词映射
        mcp_keywords = {
            "query_db": ["查询数据库", "数据库查询", "sql", "db"],
            "query_metrics": ["查询指标", "监控指标", "metrics", "cpu", "内存", "磁盘"],
            "query_sls": ["查询日志", "日志查询", "sls", "log"],
            "query_topology": ["查询拓扑", "拓扑", "依赖关系", "topology"],
            "query_k8s_events": ["查询事件", "k8s", "kubernetes", "pod"],
            "query_alert_history": ["查询告警历史", "历史告警", "告警记录"],
            "query_dev_change": ["查询变更", "变更记录", "change", "发布"],
        }

        for tool_name, keywords in mcp_keywords.items():
            for keyword in keywords:
                if keyword and keyword.lower() in alert_message:
                    # 确保不是 SOP 场景 (避免"数据库连接池耗尽"匹配到 query_db)
                    if tool_name == "query_db" and any(word in alert_message for word in ["耗尽", "过高", "异常", "故障"]):
                        continue
                    return tool_name

        return None

    def _fuzzy_match_sop(self, alert_context: dict[str, Any]) -> str | None:
        """模糊匹配 SOP - 描述包含"""
        alert_message = alert_context.get("message", "").lower()

        for sop_id, sop_info in self.sop_registry.items():
            sop_name = sop_info.get("name", "").lower()
            sop_desc = sop_info.get("description", "").lower()

            # 双向包含匹配
            if sop_name:
                if alert_message in sop_name or sop_name in alert_message:
                    return sop_id

            # 关键词重叠匹配
            if sop_desc:
                for keyword in ["连接池", "耗尽", "CPU", "过高", "内存", "磁盘", "超时"]:
                    if keyword.lower() in sop_desc and keyword.lower() in alert_message:
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
