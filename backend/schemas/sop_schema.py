"""
SOP YAML Schema 定义

五段式诊断报告:
1. 现象描述 (Symptom)
2. 根因分析 (Root Cause)
3. 影响范围 (Impact Scope)
4. 处置方案 (Remediation)
5. 复盘建议 (Post-mortem)

SOP 结构:
- sop_id: 唯一标识
- name: 名称
- description: 描述
- trigger: 触发条件
- steps: 执行步骤列表
  - id: 步骤ID
  - type: tool_call | llm_analysis | branch | interrupt | report_section
  - tool: 工具名称 (tool_call 时)
  - prompt: LLM prompt (llm_analysis 时)
  - condition: 分支条件 (branch 时)
  - message: 审批消息 (interrupt 时)
  - section: 报告段落 (report_section 时)
  - next: 下一步骤ID
  - on_error: 错误处理
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal
from enum import Enum
import yaml


class StepType(str, Enum):
    TOOL_CALL = "tool_call"
    LLM_ANALYSIS = "llm_analysis"
    BRANCH = "branch"
    INTERRUPT = "interrupt"
    REPORT_SECTION = "report_section"
    PARALLEL = "parallel"
    LOOP = "loop"


@dataclass
class StepDef:
    id: str
    type: StepType
    description: str = ""
    tool: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    prompt: str | None = None
    prompt_template: str | None = None
    condition: str | None = None
    branches: list[dict] = field(default_factory=list)
    message: str | None = None
    section: str | None = None
    next: str | None = None
    on_error: str | None = None
    parallel_steps: list[str] = field(default_factory=list)
    loop_over: str | None = None
    loop_step: str | None = None
    timeout_seconds: int = 300
    retry_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> StepDef:
        return cls(
            id=data["id"],
            type=StepType(data["type"]),
            description=data.get("description", ""),
            tool=data.get("tool"),
            tool_args=data.get("tool_args", {}),
            prompt=data.get("prompt"),
            prompt_template=data.get("prompt_template"),
            condition=data.get("condition"),
            branches=data.get("branches", []),
            message=data.get("message"),
            section=data.get("section"),
            next=data.get("next"),
            on_error=data.get("on_error"),
            parallel_steps=data.get("parallel_steps", []),
            loop_over=data.get("loop_over"),
            loop_step=data.get("loop_step"),
            timeout_seconds=data.get("timeout_seconds", 300),
            retry_count=data.get("retry_count", 0),
        )


@dataclass
class SOPDef:
    sop_id: str
    name: str
    description: str
    version: str = "1.0"
    trigger: dict[str, Any] = field(default_factory=dict)
    steps: list[StepDef] = field(default_factory=list)
    report_template: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> SOPDef:
        steps = [StepDef.from_dict(s) for s in data.get("steps", [])]
        return cls(
            sop_id=data["sop_id"],
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            trigger=data.get("trigger", {}),
            steps=steps,
            report_template=data.get("report_template", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_yaml(cls, yaml_content: str) -> SOPDef:
        data = yaml.safe_load(yaml_content)
        return cls.from_dict(data)

    @classmethod
    def from_yaml_file(cls, path: str) -> SOPDef:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_yaml(f.read())


# 五段式报告段落定义
REPORT_SECTIONS = {
    "symptom": "现象描述",
    "root_cause": "根因分析",
    "impact_scope": "影响范围",
    "remediation": "处置方案",
    "postmortem": "复盘建议",
}
