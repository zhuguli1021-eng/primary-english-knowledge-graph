# 自动出题接口与本地智能体接入指南（Codex / WorkBuddy / API / MCP）

本项目的全部出题能力统一封装在 `scripts/gen.py` 与 `scripts/api.py`，保证无论通过 **Codex、WorkBuddy、Claude Code、MCP、HTTP API 还是本地网页**，出题都严格围绕：
**知识点 + 年级 + 语料库 + 真题母题**，并执行同一套机检（年级词表、句长、答案、母题编号与防照抄相似度、盲解复核）。

---

## 一、在本地 Codex 上自动出题（免 API Key）

### 方式 A：在 Codex 对话中直接自动出题（推荐）
本仓库根目录已内置 `AGENTS.md`，且可将 `skills/english-question-gen/` 安装到 `~/.codex/skills/`。打开 Codex 进入本仓库目录，直接说：
> 「帮我按真题风格出 5 道六年级一般过去时的适当形式填空，做完盲解复核写入待审题目」

Codex 会自动执行：`kb.py task` → 仿写真题母题 → `kb.py blind` → `kb.py ingest`。

### 方式 B：命令行一步调用本地 `codex exec`
无需在 `llm.json` 填 API Key，直接运行：
```bash
python3 scripts/kb.py generate te.past_simple 6 2 5 --qtype 适当形式 --provider codex
```
也可以在 `llm.json` 中固定为默认：
```json
{"provider": "codex", "model": ""}
```
之后网页版（`python3 scripts/kb.py serve`）点击「直接出题」也会调用本地 Codex。

### 方式 C：给 Codex 配置 MCP Server
在 `~/.codex/config.toml` 中添加：
```toml
[mcp_servers.primary_english_kb]
command = "python3"
args = ["/你的仓库绝对路径/scripts/mcp_server.py"]
```
重启 Codex 后即可直接使用 `list_topics`、`get_exemplars`、`get_blueprint`、`create_task`、`get_blind_prompt`、`ingest_questions`、`generate_questions` 工具。

---

## 二、在 WorkBuddy / CodeBuddy / Claude Code 上自动出题

1. **安装技能（推荐）**：把本仓库 `skills/english-question-gen` 复制或软链接到：
   - WorkBuddy：`~/.workbuddy/skills/english-question-gen`
   - CodeBuddy：`~/.codebuddy/skills/english-question-gen`
   - Codex：`~/.codex/skills/english-question-gen`
2. **配置 MCP**（适用于支持 MCP 的 WorkBuddy / CodeBuddy / Claude Code）：
   ```json
   {
     "mcpServers": {
       "primary-english-kb": {
         "command": "python3",
         "args": ["/你的仓库绝对路径/scripts/mcp_server.py"]
       }
     }
   }
   ```
3. **命令行调用任意本地 CLI**：在 `llm.json` 中配置 `provider: "cli"`：
   ```json
   {"provider": "cli", "command": ["codebuddy", "-p"]}
   ```
   然后运行 `python3 scripts/kb.py generate te.past_simple 6 2 5 --provider cli`。

---

## 三、HTTP API 接口（保留并增强）

启动本地服务（同时提供网页和 API，仅监听 `127.0.0.1`）：
```bash
python3 scripts/kb.py serve 8765
```

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/llm-config` | 查看当前已配置的出题模型/本地 CLI 状态 |
| `GET` | `/api/topics?grade=6&domain=时态&q=过去` | 查询知识点、该年级真题考频、推荐难度、常见题型 |
| `GET` | `/api/exemplars?topic=te.past_simple&grade=6&qtype=适当形式&k=6` | 检索该知识点在该年级的真题原题（母题）与考法分布 |
| `GET` | `/api/blueprint?grade=6` | 查询该年级真卷大题结构蓝图 |
| `GET` | `/api/select?grade=6&n=20` | 按该年级真题考频加权从正式题库抽题 |
| `POST` | `/api/task` | 创建仿真题任务，返回 `task_id`、`refs`（母题）、`prompt` |
| `POST` | `/api/blind` | 传入 `task_id` 和 `reply`/`questions`，返回隐藏答案的盲解提示词 |
| `POST` | `/api/ingest` | 传入 `task_id`、`reply`/`questions`、可选 `blind`，执行全套质检并写入 `data/待审题目/` |
| `POST` | `/api/generate` | 一步调用已配置的 API 或本地 CLI 完成出题、盲解复核与待审写入 |
| `POST` | `/api/llm` | 透传提示词到本机配置的模型或请求内 `cfg`（兼容旧版网页调用） |

### 调用示例

```bash
# 1. 创建仿真题任务（拿母题和提示词）
curl -s -X POST http://127.0.0.1:8765/api/task \
  -H 'Content-Type: application/json' \
  -d '{"topic":"te.past_simple","grade":6,"difficulty":2,"n":5,"qtype":"适当形式"}'

# 2. 一步用配置好的模型或本地 Codex 出题
curl -s -X POST http://127.0.0.1:8765/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"topic":"te.past_simple","grade":6,"difficulty":2,"n":5,"qtype":"适当形式","provider":"codex","verify":true}'

# 3. 外部系统/Agent 把出好的题提交质检并写入待审
curl -s -X POST http://127.0.0.1:8765/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{"task_id":"<上一步返回的task_id>","questions":[...],"model":"my-agent"}'
```
