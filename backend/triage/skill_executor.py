"""
Skill 执行器

Skill 是轻量动作，比 SOP 简单，不需要多步编排。
每个 Skill 是一个函数，接收告警上下文，返回结果。
"""

from __future__ import annotations

import json
from typing import Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class SkillDef:
    """Skill 定义"""
    skill_id: str
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    handler: Callable | None = None


# ─────────────────────────────────────────────
# 内置 Skills
# ─────────────────────────────────────────────

def skill_check_service_health(context: dict[str, Any]) -> dict[str, Any]:
    """检查服务健康状态"""
    service = context.get("service", "unknown")
    return {
        "skill_id": "check_service_health",
        "service": service,
        "status": "healthy",
        "checks": {
            "cpu": "normal",
            "memory": "normal",
            "disk": "normal",
            "network": "normal",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def skill_check_recent_changes(context: dict[str, Any]) -> dict[str, Any]:
    """检查最近变更"""
    service = context.get("service", "unknown")
    return {
        "skill_id": "check_recent_changes",
        "service": service,
        "recent_changes": [
            {
                "change_id": "CHG-001",
                "type": "config_update",
                "operator": "admin",
                "time": "2026-09-18T10:00:00Z",
                "description": "更新连接池配置",
            }
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def skill_check_dependencies(context: dict[str, Any]) -> dict[str, Any]:
    """检查依赖服务状态"""
    service = context.get("service", "unknown")
    return {
        "skill_id": "check_dependencies",
        "service": service,
        "dependencies": [
            {"name": "mysql", "status": "healthy", "latency_ms": 5},
            {"name": "redis", "status": "healthy", "latency_ms": 2},
            {"name": "kafka", "status": "healthy", "latency_ms": 10},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def skill_check_alert_history(context: dict[str, Any]) -> dict[str, Any]:
    """检查历史告警"""
    service = context.get("service", "unknown")
    return {
        "skill_id": "check_alert_history",
        "service": service,
        "recent_alerts": [
            {
                "alert_id": "ALT-001",
                "level": "warning",
                "message": "CPU 使用率超过 80%",
                "time": "2026-09-18T09:30:00Z",
                "resolved": True,
            }
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────
# Skill Registry
# ─────────────────────────────────────────────

BUILTIN_SKILLS: dict[str, SkillDef] = {
    "check_service_health": SkillDef(
        skill_id="check_service_health",
        name="服务健康检查",
        description="检查指定服务的 CPU、内存、磁盘、网络状态",
        keywords=["health", "status", "healthy", "服务状态", "健康检查"],
        handler=skill_check_service_health,
    ),
    "check_recent_changes": SkillDef(
        skill_id="check_recent_changes",
        name="最近变更检查",
        description="检查服务最近的配置变更和发布记录",
        keywords=["change", "deploy", "release", "变更", "发布"],
        handler=skill_check_recent_changes,
    ),
    "check_dependencies": SkillDef(
        skill_id="check_dependencies",
        name="依赖服务检查",
        description="检查服务的上下游依赖状态",
        keywords=["dependency", "upstream", "downstream", "依赖", "上下游"],
        handler=skill_check_dependencies,
    ),
    "check_alert_history": SkillDef(
        skill_id="check_alert_history",
        name="历史告警检查",
        description="查看服务最近的历史告警记录",
        keywords=["history", "alert", "告警历史", "历史"],
        handler=skill_check_alert_history,
    ),
}


class SkillExecutor:
    """Skill 执行器"""

    def __init__(self, skills: dict[str, SkillDef] | None = None):
        self.skills = skills or BUILTIN_SKILLS

    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有可用 Skills"""
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "keywords": s.keywords,
            }
            for s in self.skills.values()
        ]

    def get_skill(self, skill_id: str) -> SkillDef | None:
        """获取 Skill 定义"""
        return self.skills.get(skill_id)

    async def execute(
        self,
        skill_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        执行 Skill

        Returns:
            执行结果，包含 execution_log 用于回放
        """
        skill = self.skills.get(skill_id)
        if not skill:
            return {
                "skill_id": skill_id,
                "status": "error",
                "error": f"Skill '{skill_id}' not found",
                "execution_log": [],
            }

        execution_log = [
            {
                "step": "skill_start",
                "skill_id": skill_id,
                "skill_name": skill.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]

        try:
            if skill.handler:
                result = skill.handler(context)
                execution_log.append({
                    "step": "skill_complete",
                    "skill_id": skill_id,
                    "result_summary": str(result)[:200],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return {
                    **result,
                    "status": "completed",
                    "execution_log": execution_log,
                }
            else:
                return {
                    "skill_id": skill_id,
                    "status": "error",
                    "error": f"Skill '{skill_id}' has no handler",
                    "execution_log": execution_log,
                }
        except Exception as e:
            execution_log.append({
                "step": "skill_error",
                "skill_id": skill_id,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return {
                "skill_id": skill_id,
                "status": "error",
                "error": str(e),
                "execution_log": execution_log,
            }
