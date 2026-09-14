"""
FastAPI 后端 API

提供:
1. SOP 管理 (加载、列表)
2. 诊断执行 (启动、审批、查询)
3. 历史回放 (时间旅行)
4. 工具元数据查询
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from runtime.diagnosis_runtime import DiagnosisRuntime
from schemas.sop_schema import SOPDef
from mcp_tools.tools import get_tools_metadata


# ─────────────────────────────────────────────
# 全局 Runtime 实例
# ─────────────────────────────────────────────

runtime: DiagnosisRuntime | None = None


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────

app = FastAPI(
    title="Ops Diagnosis API",
    description="运维诊断系统 - LangGraph Plan-Execute",
    version="0.1.0",
)

# CORS
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
    """启动时初始化 runtime"""
    global runtime
    runtime = DiagnosisRuntime(db_path="diagnosis.db")
    await runtime.initialize()

    # 自动加载 sops 目录下的所有 SOP
    sops_dir = Path(__file__).parent.parent / "sops"
    if sops_dir.exists():
        for sop_file in sops_dir.glob("*.yaml"):
            try:
                await runtime.load_sop_from_file(str(sop_file))
                print(f"Loaded SOP: {sop_file.name}")
            except Exception as e:
                print(f"Failed to load SOP {sop_file.name}: {e}")


@app.on_event("shutdown")
async def shutdown():
    """关闭时清理 runtime"""
    if runtime:
        await runtime.close()


# ─────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────

class StartDiagnosisRequest(BaseModel):
    sop_id: str
    alert_context: dict[str, Any]


class ApproveInterruptRequest(BaseModel):
    approved: bool
    comment: str = ""


class ReplayRequest(BaseModel):
    checkpoint_id: str


# ─────────────────────────────────────────────
# SOP 管理 API
# ─────────────────────────────────────────────

@app.get("/api/sops")
async def list_sops():
    """列出所有已加载的 SOP"""
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
    """获取 SOP 详情"""
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


@app.post("/api/sops/load")
async def load_sop(yaml_content: str):
    """从 YAML 内容加载 SOP"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    try:
        sop_id = await runtime.load_sop_from_yaml(yaml_content)
        return {"sop_id": sop_id, "status": "loaded"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────
# 诊断执行 API
# ─────────────────────────────────────────────

@app.post("/api/diagnosis/start")
async def start_diagnosis(request: StartDiagnosisRequest):
    """启动诊断流程"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    try:
        result = await runtime.start_diagnosis(
            sop_id=request.sop_id,
            alert_context=request.alert_context,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/diagnosis/{thread_id}")
async def get_diagnosis(thread_id: str):
    """获取诊断 thread 当前状态"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    try:
        state = await runtime.get_thread_state(thread_id)
        return state
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/diagnosis/{thread_id}/approve")
async def approve_interrupt(thread_id: str, request: ApproveInterruptRequest):
    """审批 interrupt (人工闸门)"""
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
# 历史与回放 API
# ─────────────────────────────────────────────

@app.get("/api/threads")
async def list_threads():
    """列出所有诊断 thread"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    threads = await runtime.list_threads()
    return {"threads": threads}


@app.get("/api/threads/{thread_id}/history")
async def get_thread_history(thread_id: str):
    """获取 thread 执行历史 (时间旅行)"""
    if not runtime:
        raise HTTPException(status_code=500, detail="Runtime not initialized")

    try:
        history = await runtime.get_thread_history(thread_id)
        return {"thread_id": thread_id, "history": history}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/threads/{thread_id}/replay")
async def replay_to_checkpoint(thread_id: str, request: ReplayRequest):
    """回放到指定 checkpoint"""
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
# 工具 API
# ─────────────────────────────────────────────

@app.get("/api/tools")
async def list_tools():
    """列出所有可用工具"""
    tools = get_tools_metadata()
    return {"tools": tools}


# ─────────────────────────────────────────────
# 静态文件服务 (SPA)
# ─────────────────────────────────────────────

# 前端构建输出目录
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


@app.get("/")
async def serve_spa():
    """提供 SPA 入口"""
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not built. Run 'cd frontend && npm run build'"}


# 挂载静态文件
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


# ─────────────────────────────────────────────
# 健康检查
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "runtime_initialized": runtime is not None,
        "sops_loaded": len(runtime.compiled_graphs) if runtime else 0,
    }
