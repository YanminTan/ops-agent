"""
MCP 工具定义

模拟 MCP 工具接口，用于从多数据源采集事实。
实际部署时替换为真实 MCP client 调用。
"""

from __future__ import annotations
from typing import Any
import json
import random
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# 工具注册表
# ─────────────────────────────────────────────

TOOLS_REGISTRY: dict[str, callable] = {}


def register_tool(name: str):
    """工具注册装饰器"""
    def decorator(fn):
        TOOLS_REGISTRY[name] = fn
        fn._tool_name = name
        return fn
    return decorator


# ─────────────────────────────────────────────
# MCP 工具实现 (模拟层)
# ─────────────────────────────────────────────

@register_tool("query_db")
async def query_db(query: str = "", database: str = "default", **kwargs) -> dict[str, Any]:
    """
    查询数据库 - 从指定数据库执行查询
    MCP Tool: query_db
    """
    # 模拟返回
    return {
        "tool": "query_db",
        "database": database,
        "query": query,
        "rows": [
            {"id": 1, "metric": "cpu_usage", "value": 85.2, "timestamp": "2026-09-14T10:00:00Z"},
            {"id": 2, "metric": "memory_usage", "value": 72.1, "timestamp": "2026-09-14T10:00:00Z"},
            {"id": 3, "metric": "disk_io", "value": 45.6, "timestamp": "2026-09-14T10:00:00Z"},
        ],
        "row_count": 3,
        "execution_time_ms": random.randint(50, 500),
    }


@register_tool("query_dev_change")
async def query_dev_change(service: str = "", time_range: str = "24h", **kwargs) -> dict[str, Any]:
    """
    查询设备/服务变更记录
    MCP Tool: query_dev_change
    """
    return {
        "tool": "query_dev_change",
        "service": service,
        "time_range": time_range,
        "changes": [
            {
                "change_id": "CHG-20260914-001",
                "type": "deployment",
                "service": service or "api-gateway",
                "version": "v2.3.1 -> v2.3.2",
                "operator": "deploy-bot",
                "timestamp": "2026-09-14T08:30:00Z",
                "status": "completed",
                "rollback_available": True,
            },
            {
                "change_id": "CHG-20260914-002",
                "type": "config_change",
                "service": service or "api-gateway",
                "detail": "rate_limit: 1000 -> 2000",
                "operator": "admin",
                "timestamp": "2026-09-14T09:15:00Z",
                "status": "completed",
                "rollback_available": True,
            },
        ],
        "total": 2,
    }


@register_tool("query_sls")
async def query_sls(project: str = "", logstore: str = "", query: str = "", time_range: str = "1h", **kwargs) -> dict[str, Any]:
    """
    查询日志服务 (SLS)
    MCP Tool: query_sls
    """
    return {
        "tool": "query_sls",
        "project": project,
        "logstore": logstore,
        "query": query,
        "time_range": time_range,
        "logs": [
            {
                "timestamp": "2026-09-14T10:05:23Z",
                "level": "ERROR",
                "service": "order-service",
                "message": "Connection timeout to database: 10.0.1.50:3306",
                "trace_id": "abc123def456",
            },
            {
                "timestamp": "2026-09-14T10:05:25Z",
                "level": "WARN",
                "service": "order-service",
                "message": "Retry attempt 3/5 for database connection",
                "trace_id": "abc123def456",
            },
            {
                "timestamp": "2026-09-14T10:06:01Z",
                "level": "ERROR",
                "service": "order-service",
                "message": "Circuit breaker OPEN for database connection",
                "trace_id": "abc123def456",
            },
        ],
        "total": 3,
        "aggregations": {
            "error_count": 156,
            "warn_count": 342,
            "affected_services": ["order-service", "payment-service"],
        },
    }


@register_tool("query_metrics")
async def query_metrics(metric: str = "", service: str = "", time_range: str = "1h", **kwargs) -> dict[str, Any]:
    """
    查询监控指标
    MCP Tool: query_metrics
    """
    return {
        "tool": "query_metrics",
        "metric": metric,
        "service": service,
        "time_range": time_range,
        "data_points": [
            {"timestamp": "2026-09-14T09:00:00Z", "value": 45.2},
            {"timestamp": "2026-09-14T09:15:00Z", "value": 52.8},
            {"timestamp": "2026-09-14T09:30:00Z", "value": 78.3},
            {"timestamp": "2026-09-14T09:45:00Z", "value": 92.1},
            {"timestamp": "2026-09-14T10:00:00Z", "value": 95.7},
        ],
        "summary": {
            "avg": 72.8,
            "max": 95.7,
            "min": 45.2,
            "p99": 94.2,
            "trend": "rising",
        },
    }


@register_tool("query_topology")
async def query_topology(service: str = "", depth: int = 2, **kwargs) -> dict[str, Any]:
    """
    查询服务拓扑依赖
    MCP Tool: query_topology
    """
    return {
        "tool": "query_topology",
        "service": service,
        "depth": depth,
        "topology": {
            "nodes": [
                {"id": "api-gateway", "type": "service", "status": "healthy"},
                {"id": "order-service", "type": "service", "status": "degraded"},
                {"id": "payment-service", "type": "service", "status": "healthy"},
                {"id": "mysql-primary", "type": "database", "status": "unhealthy"},
                {"id": "redis-cache", "type": "cache", "status": "healthy"},
            ],
            "edges": [
                {"from": "api-gateway", "to": "order-service", "latency_ms": 45},
                {"from": "order-service", "to": "mysql-primary", "latency_ms": 5000},
                {"from": "order-service", "to": "redis-cache", "latency_ms": 2},
                {"from": "order-service", "to": "payment-service", "latency_ms": 30},
            ],
        },
    }


@register_tool("query_k8s_events")
async def query_k8s_events(namespace: str = "", pod: str = "", time_range: str = "1h", **kwargs) -> dict[str, Any]:
    """
    查询 Kubernetes 事件
    MCP Tool: query_k8s_events
    """
    return {
        "tool": "query_k8s_events",
        "namespace": namespace,
        "time_range": time_range,
        "events": [
            {
                "timestamp": "2026-09-14T10:03:00Z",
                "type": "Warning",
                "reason": "Unhealthy",
                "message": "Readiness probe failed: connection refused",
                "object": "pod/order-service-7d8f9c6b5-x2k4j",
            },
            {
                "timestamp": "2026-09-14T10:04:30Z",
                "type": "Warning",
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "object": "pod/order-service-7d8f9c6b5-x2k4j",
            },
        ],
        "total": 2,
    }


@register_tool("query_alert_history")
async def query_alert_history(service: str = "", time_range: str = "7d", **kwargs) -> dict[str, Any]:
    """
    查询历史告警
    MCP Tool: query_alert_history
    """
    return {
        "tool": "query_alert_history",
        "service": service,
        "time_range": time_range,
        "alerts": [
            {
                "alert_id": "ALT-20260913-001",
                "rule": "high_cpu_usage",
                "severity": "warning",
                "service": service or "order-service",
                "message": "CPU usage > 80% for 5 minutes",
                "timestamp": "2026-09-13T14:30:00Z",
                "resolved": True,
                "resolution_time_min": 15,
            },
            {
                "alert_id": "ALT-20260912-003",
                "rule": "db_connection_pool_exhausted",
                "severity": "critical",
                "service": service or "order-service",
                "message": "Database connection pool exhausted",
                "timestamp": "2026-09-12T09:00:00Z",
                "resolved": True,
                "resolution_time_min": 45,
            },
        ],
        "total": 2,
    }


# ─────────────────────────────────────────────
# 工具元数据 (供前端展示)
# ─────────────────────────────────────────────

def get_tools_metadata() -> list[dict]:
    """获取所有工具的元数据"""
    metadata = []
    for name, fn in TOOLS_REGISTRY.items():
        doc = fn.__doc__ or ""
        metadata.append({
            "name": name,
            "description": doc.strip().split("\n")[0] if doc else name,
            "full_description": doc.strip() if doc else name,
        })
    return metadata
