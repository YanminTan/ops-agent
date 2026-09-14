#!/bin/bash

# 运维诊断系统启动脚本
# 单端口 :9100 同时 serve API 和 SPA

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🚀 启动运维诊断系统..."

# 检查 Python 依赖
echo "📦 检查 Python 依赖..."
cd "$PROJECT_DIR/backend"
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "安装 Python 依赖..."
    pip3 install -r requirements.txt
fi

# 检查前端依赖
echo "📦 检查前端依赖..."
cd "$PROJECT_DIR/frontend"
if [ ! -d "node_modules" ]; then
    echo "安装前端依赖..."
    npm install
fi

# 构建前端
echo "🔨 构建前端..."
npm run build

# 启动后端（同时 serve API 和静态文件）
echo "🎯 启动服务 (http://localhost:9100)..."
cd "$PROJECT_DIR/backend"

# 创建启动文件
cat > start_server.py << 'EOF'
import uvicorn
from pathlib import Path
import sys

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent))

from api.main import app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 挂载前端静态文件
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    # 挂载 assets
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    
    # 重写根路由，提供 SPA
    @app.get("/")
    async def serve_spa():
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "Frontend not built"}
    
    # SPA fallback: 所有非 API 路由返回 index.html
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        if path.startswith("api/") or path.startswith("assets/"):
            return {"error": "Not found"}
        
        # 尝试返回静态文件
        file_path = frontend_dist / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        
        # 否则返回 index.html (SPA routing)
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        
        return {"error": "Not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9100)
EOF

python3 start_server.py
