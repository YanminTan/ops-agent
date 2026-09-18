# 运维诊断系统

> **生产级运维 Agent 的最小可运行 Demo** — 阿里云 VPC/CEN 管控面运维智能助手的核心架构开源

## 🏆 生产环境成果

| 指标 | 数据 |
|------|------|
| 月调用 | **500+ 次**，平均耗时 96s |
| 替代人力 | 触达 11 人，替代 5.1-9.1 期间每天 2 人值班，累计节省约 **240 人天** |
| 成本优化 | 输入 token **↓89%~93%**，单任务成本 **↓91%~99%**，端到端耗时 **↓39%~73%** |

## ⚡ 核心亮点

- **SOP 计划优先的三层路由**：高频告警写成 YAML → 编译成 LangGraph 图 → 确定性代码节点，每步带 gate 校验；无计划走 Skill 引导的有界 ReAct；再没有才限轮自由探索。主链路 LLM **固定调 2 次**
- **代码知识 RAG**：管控面 Java 代码按方法切块向量化入 Qdrant，诊断时按"最慢阶段"检索代码，把方法签名、日志点、DB 操作注入报告
- **安全闭环**：写操作经受控提单 + 人审批 + 幂等执行 + Verifier 五方对账，变更类误伤率 = 0；microVM + STS + namespace 四层隔离 + 命令白名单
- **工程化**：651 个单测，含 good case 回放与 bad case（注入/脏数据）；断点续跑；全链路 trace 并按节点统计成本

## 🚀 快速体验

```bash
# 1. 安装依赖
cd backend && pip3 install -r requirements.txt
cd ../frontend && npm install

# 2. 启动（单端口 :9100）
./scripts/start.sh

# 3. 打开浏览器
open http://localhost:9100
```

### 一键测试三层路由

```bash
# SOP 路由：告警自动匹配诊断流程
curl -X POST http://localhost:9100/api/diagnosis/start \
  -H "Content-Type: application/json" \
  -d '{"alert_context": {"message": "数据库连接池耗尽", "service": "order-service"}}'

# Skill 路由：轻量动作直接执行
curl -X POST http://localhost:9100/api/diagnosis/start \
  -H "Content-Type: application/json" \
  -d '{"alert_context": {"message": "服务健康检查", "service": "api-gateway"}}'

# MCP 路由：单点工具直调
curl -X POST http://localhost:9100/api/diagnosis/start \
  -H "Content-Type: application/json" \
  -d '{"route": "mcp", "sop_id": "query_metrics", "alert_context": {"service": "order-service"}}'
```

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      声明式 SOP YAML                         │
│  (定义诊断流程：数据收集 → 分析 → 审批 → 报告生成)              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    SOP Compiler                              │
│  (YAML → LangGraph StateGraph，确定性编译)                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                 Diagnosis Runtime                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  LangGraph StateGraph 执行引擎                        │  │
│  │  - tool_call: 调用 MCP 工具采集事实                    │  │
│  │  - llm_analysis: LLM 分析生成洞察                     │  │
│  │  - interrupt: 人工审批闸门（写路径分离）                │  │
│  │  - report_section: 生成报告段落                       │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  SQLite Checkpointer                                 │  │
│  │  - 每个 thread 的完整状态持久化                        │  │
│  │  - 支持时间旅行回放                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP Tools (数据源)                        │
│  - query_db: 查询数据库                                     │
│  - query_dev_change: 查询变更记录                            │
│  - query_sls: 查询日志服务                                   │
│  - query_metrics: 查询监控指标                               │
│  - query_topology: 查询服务拓扑                              │
│  - query_k8s_events: 查询 K8s 事件                          │
│  - query_alert_history: 查询历史告警                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                 五段式诊断报告                                │
│  1. 现象描述 (Symptom)                                       │
│  2. 根因分析 (Root Cause)                                    │
│  3. 影响范围 (Impact Scope)                                  │
│  4. 处置方案 (Remediation)                                   │
│  5. 复盘建议 (Post-mortem)                                   │
└─────────────────────────────────────────────────────────────┘
```

## 关键设计决策

### 1. 读路径与写路径彻底分离

- **读路径**: 所有数据采集（tool_call）和 LLM 分析自动执行，无需人工干预
- **写路径**: 所有写操作（如重启服务、扩容、回滚）必须经过 `interrupt()` 人工审批闸门
- 通过 LangGraph 的 interrupt 原语实现，确保写操作的可控性

### 2. 声明式 SOP 编排

- SOP 使用 YAML 定义，无需编写代码
- Compiler 将 YAML 编译为确定性的 StateGraph
- 支持 tool_call / llm_analysis / branch / interrupt / report_section 等步骤类型
- 支持步骤间的依赖和数据传递（通过 `${var}` 模板语法）

### 3. 完整的状态持久化

- 每个诊断 thread 的完整执行状态持久化到 SQLite checkpointer
- 支持任意步骤的时间旅行回放
- 可以查看每个 checkpoint 的完整状态快照

### 4. 单端口部署

- 前端 React + Vite 构建为静态文件
- 后端 FastAPI 同时 serve API 和 SPA
- 单端口 `:9100` 同时提供所有服务

## 项目结构

```
ops-diagnosis/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI 后端 API
│   ├── compiler/
│   │   └── sop_compiler.py      # SOP Compiler (YAML → StateGraph)
│   ├── runtime/
│   │   └── diagnosis_runtime.py # 诊断执行引擎
│   ├── schemas/
│   │   └── sop_schema.py        # SOP YAML Schema 定义
│   ├── mcp_tools/
│   │   └── tools.py             # MCP 工具定义（模拟层）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── AlertAnalysis.jsx    # 告警分析页面
│   │   │   ├── HistoryBrowser.jsx   # 历史浏览页面
│   │   │   └── ReplayViewer.jsx     # 逐帧回放页面
│   │   ├── App.jsx
│   │   ├── api.js               # API 客户端
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── sops/
│   ├── db-connection-pool.yaml  # 示例 SOP: 数据库连接池耗尽
│   └── high-cpu-usage.yaml      # 示例 SOP: CPU 使用率过高
├── scripts/
│   └── start.sh                 # 启动脚本
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
# 后端依赖
cd backend
pip3 install -r requirements.txt

# 前端依赖
cd ../frontend
npm install
```

### 2. 启动服务

```bash
# 使用启动脚本（推荐）
./scripts/start.sh

# 或手动启动
cd backend
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 9100
```

### 3. 访问系统

打开浏览器访问 `http://localhost:9100`

## 使用示例

### 1. 告警分析

1. 选择 SOP（如"数据库连接池耗尽诊断"）
2. 填写告警信息（来源、级别、消息、影响服务）
3. 点击"开始诊断"
4. 系统自动执行数据采集和分析
5. 遇到需要人工审批的步骤时，点击"批准"或"拒绝"
6. 查看生成的五段式诊断报告

### 2. 历史浏览

- 查看所有诊断记录
- 查看每个诊断的详细信息
- 跳转到逐帧回放

### 3. 逐帧回放

- 查看诊断执行的每个步骤
- 查看每个 checkpoint 的完整状态
- 支持前进/后退导航
- 查看时间线

## SOP YAML 语法

### 基本结构

```yaml
sop_id: unique-id
name: SOP 名称
description: SOP 描述
version: "1.0"

trigger:
  alert_rule: 告警规则名
  severity: critical|warning|info
  conditions:
    - metric: 指标名
      operator: ">="
      threshold: 80

steps:
  - id: step_id
    type: tool_call|llm_analysis|branch|interrupt|report_section
    description: 步骤描述
    # ... 其他配置
```

### 步骤类型

#### tool_call - 工具调用

```yaml
- id: collect_metrics
  type: tool_call
  description: 收集监控指标
  tool: query_metrics
  tool_args:
    metric: "cpu_usage"
    service: "${alert_context.service}"
  next: next_step_id
```

#### llm_analysis - LLM 分析

```yaml
- id: analyze_root_cause
  type: llm_analysis
  description: 根因分析
  prompt_template: |
    基于以下事实分析根因：
    事实1: ${collected_facts.step1}
    事实2: ${collected_facts.step2}
  next: next_step_id
```

#### interrupt - 人工审批

```yaml
- id: approval_step
  type: interrupt
  description: 处置方案审批
  message: "请审批处置方案：是否执行 xxx？"
  next: next_step_id
```

#### report_section - 报告段落

```yaml
- id: generate_symptom
  type: report_section
  description: 生成现象描述
  section: symptom  # symptom|root_cause|impact_scope|remediation|postmortem
  next: next_step_id
```

### 变量引用

使用 `${var}` 语法引用上下文变量：

- `${alert_context.service}` - 引用告警上下文中的 service
- `${collected_facts.step_id}` - 引用某步骤收集的事实
- `${step_results.step_id}` - 引用某步骤的执行结果

## API 文档

启动服务后访问 `http://localhost:9100/docs` 查看完整的 API 文档。

### 主要 API

- `GET /api/sops` - 列出所有 SOP
- `POST /api/diagnosis/start` - 启动诊断
- `GET /api/diagnosis/{thread_id}` - 获取诊断状态
- `POST /api/diagnosis/{thread_id}/approve` - 审批 interrupt
- `GET /api/threads` - 列出所有诊断 thread
- `GET /api/threads/{thread_id}/history` - 获取执行历史
- `POST /api/threads/{thread_id}/replay` - 回放到指定 checkpoint

## 开发计划

- [ ] 集成真实的 MCP 工具（替换模拟层）
- [ ] 集成真实的 LLM（OpenAI / Claude / 本地模型）
- [ ] 支持更复杂的 SOP 语法（并行、循环、条件分支）
- [ ] 添加 SOP 编辑器（可视化编辑）
- [ ] 添加告警源集成（Prometheus AlertManager / Grafana）
- [ ] 添加通知集成（Slack / 钉钉 / 企业微信）

## 技术栈

- **后端**: Python 3.10+, FastAPI, LangGraph, SQLite
- **前端**: React 18, Vite, React Router
- **架构**: LangGraph Plan-Execute, MCP Tools, SQLite Checkpointer

## License

MIT
