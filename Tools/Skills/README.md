# AiNiee Skills — 轻量级 AI 工具调用框架

一套轻量的、**不依赖 MCP** 的 AiNiee 交互框架。Skills 通过简洁的 REST/JSON 接口暴露核心功能，无需 MCP 协议、FastAPI 或 uvicorn。

## 为什么用 Skills 而不是 MCP？

MCP 服务器（`Tools/MCPServer/`）是一套完整的 [Model Context Protocol](https://modelcontextprotocol.io) 实现，需要：
- `mcp` Python 包（FastMCP）
- `fastapi` + `uvicorn` 提供 HTTP 传输
- JSON-RPC 2.0 消息格式
- 从 WebServer 自动发现路由

Skills 则完全不同：
- **零额外服务依赖** — HTTP 层仅用 Python 标准库（`http.server`、`json`），业务层复用项目现有模块
- **简洁 REST/JSON** — 不是 JSON-RPC，就是 HTTP + JSON
- **精选操作** — 预定义的 skill 覆盖核心工作流，不自动暴露所有路由
- **多种执行模式** — 可通过 HTTP 服务、CLI、或直接 Python 调用
- **可组合** — skill 可串联调用，适合脚本自动化

## 快速开始

### 启动 Skills Server

命令行启动：
```bash
python Tools/Skills/server.py --port 8766
```

默认情况下，`POST /skills/{name}` 需要鉴权。服务启动时会在终端输出本次运行的
`X-AiNiee-Skills-Auth` token；也可以用环境变量固定 token：

```bash
AINIEE_SKILLS_AUTH_TOKEN="your-token" python Tools/Skills/server.py --port 8766
```

只在可信本机调试时，可以用 `--no-auth` 临时关闭 HTTP 鉴权。

或用启动脚本：
```bash
bash Tools/Skills/launcher.sh --port 8766
```

### 检查服务是否运行

```bash
curl http://127.0.0.1:8766/health
```

返回：
```json
{"status": "ok", "service": "ainiee-skills", "skills_count": 6}
```

### 查看可用 Skills

```bash
curl http://127.0.0.1:8766/skills
```

## 内置 Skills

| Skill | 分类 | 说明 |
|-------|------|------|
| `system` | system | 系统信息与健康检查 |
| `config` | config | 读写配置文件的设置项 |
| `translate` | task | 执行翻译任务 |
| `queue` | queue | 管理项目内置任务队列（`Resource/queue_tasks.json`） |
| `profile` | config | 管理配置方案（新建/切换/删除，自动限制在 profiles 目录内） |
| `file` | files | 文件发现与暂存 |

## API 参考

### `GET /health`
健康检查端点。

### `GET /skills`
列出所有可用的 skill，包含说明、参数和示例。

### `GET /skills/{name}`
获取指定 skill 的详细信息。

**示例：**
```bash
curl http://127.0.0.1:8766/skills/system
```

### `POST /skills/{name}`
执行一个 skill，传入参数。

**Ping：**
```bash
curl -X POST http://127.0.0.1:8766/skills/system \
  -H "Content-Type: application/json" \
  -H "X-AiNiee-Skills-Auth: your-token" \
  -d '{"action": "ping"}'
```
返回：
```json
{"success": true, "data": {"pong": true}}
```

**读取配置：**
```bash
curl -X POST http://127.0.0.1:8766/skills/config \
  -H "Content-Type: application/json" \
  -H "X-AiNiee-Skills-Auth: your-token" \
  -d '{"action": "get", "key": "target_platform"}'
```

**列出配置方案：**
```bash
curl -X POST http://127.0.0.1:8766/skills/profile \
  -H "Content-Type: application/json" \
  -H "X-AiNiee-Skills-Auth: your-token" \
  -d '{"action": "list"}'
```

**启动翻译：**
```bash
curl -X POST http://127.0.0.1:8766/skills/translate \
  -H "Content-Type: application/json" \
  -H "X-AiNiee-Skills-Auth: your-token" \
  -d '{
    "action": "run",
    "task_type": "translate",
    "input_path": "/path/to/file.txt",
    "source_lang": "Japanese",
    "target_lang": "Chinese",
    "profile": "default"
  }'
```

## CLI 模式

不启动 HTTP 服务也能直接调用 skill：

```bash
# 列出所有 skill
python Tools/Skills/cli.py list

# 查看 skill 详情
python Tools/Skills/cli.py describe config

# 执行 skill
python Tools/Skills/cli.py run system '{"action": "ping"}'

# 启动 HTTP 服务
python Tools/Skills/cli.py server --port 8766
```

## 目录结构

```
Tools/Skills/
├── README.md              # 本文档
├── __init__.py            # 包导出
├── skill_base.py          # Skill、SkillRegistry、SkillResult 基类
├── server.py              # HTTP 服务（基于 stdlib http.server）
├── cli.py                 # CLI 运行器
├── runtime.py             # 运行环境检查
├── launcher.sh            # Shell 启动脚本
└── skills/
    ├── __init__.py        # 注册中心（注册所有 skill）
    ├── system_skill.py    # 系统信息与健康检查
    ├── config_skill.py    # 配置管理
    ├── translate_skill.py # 翻译任务执行
    ├── queue_skill.py     # 任务队列管理
    ├── profile_skill.py   # 配置方案管理
    └── file_skill.py      # 文件操作
```

## 执行模式（混合模式）

Skills 支持三种执行模式，自动选择：

1. **直接调用（首选）**：进程内直接调用 AiNiee 内部 API
2. **CLI 子进程**：通过 `uv run ainiee_cli.py` 子进程执行任务
3. **WebServer 代理**：通过 WebServer HTTP API 代理调用

## MCP 与 Skills 对比

| 特性 | MCP Server | Skills Server |
|------|-----------|---------------|
| 协议 | JSON-RPC 2.0 | REST/JSON |
| 依赖 | mcp、fastapi、uvicorn | 仅标准库 |
| 传输层 | stdio / streamable-http / SSE | HTTP |
| 路由发现 | 自动（全部 /api/*） | 手动精选 |
| 执行模式 | WebServer 代理 | 直接 / CLI / WebServer |
| 默认端口 | 8765 | 8766 |

## 扩展：添加新的 Skill

1. 在 `Tools/Skills/skills/` 下新建文件（如 `my_skill.py`）
2. 继承 `Skill` 基类，实现 `meta` 和 `execute`
3. 在 `Tools/Skills/skills/__init__.py` 中注册

示例：

```python
from Tools.Skills.skill_base import Skill, SkillMeta, SkillParameter, SkillResult

class MySkill(Skill):
    @property
    def meta(self):
        return SkillMeta(
            name="my_skill",
            description="做些有用的事。",
            category="custom",
            parameters=[SkillParameter(name="input", type="string", required=True)],
        )

    def execute(self, args):
        return SkillResult.ok({"processed": args.get("input", "")})
```
