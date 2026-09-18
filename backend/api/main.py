"""
FastAPI 后端 API (三层路由版)

提供:
1. 意图分类 (triage)
2. SOP 管理 (加载、列表)
3. Skill 管理 (列表)
4. MCP 工具管理 (列表)
5. 统一诊断执行 (SOP / Skill / MCP 三路)
6. 审批 (SOP 路径 interrupt)
7. 统一回放 (三路)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from runtime.diagnosis_runtime import DiagnosisRuntime
from schemas.sop_schema import SOPDef
from mcp_tools.tools import get_tools_metadata
from triage.skill_executor import BUILTIN_SKILLS


# ─────────────────────────────────────────────
# 全局 Runtime 实例
# ─────────────────────────────────────────────

runtime: DiagnosisRuntime | None = None


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(
    title="Ops Diagnosis API (三层路由)",
    description="运维诊断系统 - 意图分类 + SOP/Skill/MCP 三路路由",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# 生命周期
# ─────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global runtime
    runtime = DiagnosisRuntime(db_path="diagnosis.db")
    await runtime.initialize()

    sops_dir = Path(__file__).parent.parent.parent / "sops"
    if sops_dir.exists():
        for sop_file in sops_dir.glob("*.yaml"):
            try:
                await runtime.load_sop_from_file(str(sop_file))
                print(f"Loaded SOP: {sop_file.name}")
            except Exception as e:
                print(f"Failed to load SOP {sop_file.name}: {e}")

    # 重新初始化 triage (加载完 SOP 后)
    await runtime.initialize()


@app.on_event("shutdown")
async def shutdown():
    if runtime:
        await runtime.close()


# ─────────────────────────────────────────────
# 请求模型
# ─────────────────────────────────────────────

class TriageRequest(BaseModel):
    alert_context: dict[str, Any]


class StartDiagnosisRequest(BaseModel):
    sop_id: str | None = None
    alert_context: dict[str, Any] | None = None
    route: str | None = None  # 强制路由: sop / skill / mcp


class ApproveInterruptRequest(BaseModel):
    approved: bool
    comment: str = ""


class ReplayRequest(BaseModel):
    checkpoint_id: str


# ─────────────────────────────────────────────
# 意图分类 API
# ─────────────────────────────────────────────

@app.post("/api/triage")
async def triage(request: TriageRequest):
    """意图分类: 将告警路由到 SOP / Skill / MCP"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    result = await runtime.triage_alert(request.alert_context)
    return result.to_dict()


# ─────────────────────────────────────────────
# SOP 管理 API
# ─────────────────────────────────────────────

@app.get("/api/sops")
async def list_sops():
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    sops = []
    for sop_id, sop_def in runtime.sop_defs.items():
        sops.append({
            "sop_id": sop_id,
            "name": sop_def.name,
            "description": sop_def.description,
            "version": sop_def.version,
            "steps_count": len(sop_def.steps),
        })
    return {"sops": sops}


@app.get("/api/sops/{sop_id}")
async def get_sop(sop_id: str):
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    if sop_id not in runtime.sop_defs:
        raise HTTPException(status_code=404, detail=f"SOP '{sop_id}' not found")
    sop = runtime.sop_defs[sop_id]
    return {
        "sop_id": sop.sop_id,
        "name": sop.name,
        "description": sop.description,
        "version": sop.version,
        "trigger": sop.trigger,
        "steps": [
            {
                "id": step.id,
                "type": step.type.value,
                "description": step.description,
                "tool": step.tool,
                "next": step.next,
            }
            for step in sop.steps
        ],
    }


# ─────────────────────────────────────────────
# Skill 管理 API
# ─────────────────────────────────────────────

@app.get("/api/skills")
async def list_skills():
    """列出所有可用 Skills"""
    skills = [
        {
            "skill_id": s.skill_id,
            "name": s.name,
            "description": s.description,
            "keywords": s.keywords,
        }
        for s in BUILTIN_SKILLS.values()
    ]
    return {"skills": skills}


# ─────────────────────────────────────────────
# MCP 工具 API
# ─────────────────────────────────────────────

@app.get("/api/tools")
async def list_tools():
    tools = get_tools_metadata()
    return {"tools": tools}


# ────────────────────────────────────────────
# 统一诊断执行 API
# ─────────────────────────────────────────────

@app.post("/api/diagnosis/start")
async def start_diagnosis(request: StartDiagnosisRequest):
    """
    统一诊断入口 (三层路由)

    调用方式:
    1. 指定 sop_id → 直接走 SOP 路径
    2. 提供 alert_context → 自动 triage 后路由
    3. 指定 route + sop_id → 强制路由 (测试用)
    """
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    try:
        result = await runtime.start_diagnosis(
            sop_id=request.sop_id,
            alert_context=request.alert_context,
            route=request.route,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diagnosis/{thread_id}")
async def get_diagnosis(thread_id: str):
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    try:
        state = await runtime.get_thread_state(thread_id)
        return state
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/diagnosis/{thread_id}/approve")
async def approve_interrupt(thread_id: str, request: ApproveInterruptRequest):
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    try:
        result = await runtime.approve_interrupt(
            thread_id=thread_id,
            approved=request.approved,
            comment=request.comment,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# 统一回放 API (三路)
# ─────────────────────────────────────────────

@app.get("/api/threads")
async def list_threads():
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    threads = await runtime.list_threads()
    return {"threads": threads}


@app.get("/api/threads/{thread_id}/history")
async def get_thread_history(thread_id: str):
    """获取 thread 执行历史 (三路统一回放)"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    try:
        history = await runtime.get_thread_history(thread_id)
        return {"thread_id": thread_id, "history": history}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/threads/{thread_id}/replay")
async def replay_to_checkpoint(thread_id: str, request: ReplayRequest):
    """回放到指定 checkpoint (三路统一)"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")
    try:
        result = await runtime.replay_to_checkpoint(
            thread_id=thread_id,
            checkpoint_id=request.checkpoint_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# 静态文件服务 (SPA)
# ─────────────────────────────────────────────

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@app.get("/")
async def serve_spa():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built. Run 'cd frontend && npm run build'"}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "runtime_initialized": runtime is not None,
        "sops_loaded": len(runtime.sop_defs) if runtime else 0,
        "skills_loaded": len(BUILTIN_SKILLS),
        "mcp_tools": len(get_tools_metadata()),
    }
