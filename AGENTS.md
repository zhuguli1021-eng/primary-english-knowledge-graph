# 小学英语知识图谱 · 智能体出题与教研规范（Codex / WorkBuddy / Claude Code）

教师作业生成器按 G0–G3 的级别、单元和知识板块抽取已有公立校原题。年级映射和固定题量以 `scripts/homework_bank.py` 的 CONFIG 为准。教师界面一次出三档卷，无分值，题库不足时展示实际数量。G0 适用 5–6 岁、G1 适用 6–8 岁、G2 适用 8–10 岁。抽卷先按单元筛适龄原题，再按 L/M/H 的来源年级出卷。G0 可由大人读题，缺少适龄原题的板块或整档留空，等教研补充。内部单元测、新编题与待审题均不进入此入口。

以下规范用于教研后台编写新题和维护题库。

教研人员编写新题**必须**同时围绕四个核心依据：
1. **知识点**（`data/topics.json`）：说明、掌握标准、常见错误
2. **年级**（`data/levels.json`）：词表分级、单句词数上限、已学语法（首学年级晚于学生年级的知识点不出）
3. **语料库**（`corpus/`、`data/corpus_index.json`、`data/exam_stats.json`）：分年级真卷考频与考法分布
4. **真题原题（母题）**（`data/exam_items.json`、`data/exam_blueprint.json`）：逐题仿写真题的考查角度、句子结构、设空位置与选项设计，**不得照抄**

> **禁止凭空出题。** 任何出题请求都必须先通过 `kb.py task`（或 MCP 工具 `create_task`）检索真题母题并锁定约束，出题后必须通过 `kb.py ingest`（或 MCP 工具 `ingest_questions`）做全套质检再写入 `data/待审题目/`。

## 标准自动出题流程（本地智能体模式，免 API Key）

当用户让你出题（例如「帮我出 5 道六年级一般过去时的适当形式填空」或「按小升初真卷出一套题」）时，严格按以下 4 步执行：

1. **查知识点与年级考法**（如不确定知识点 id 或题型）：
   ```bash
   python3 scripts/kb.py topics --grade 6 --q 过去时
   python3 scripts/kb.py exemplars te.past_simple 6
   python3 scripts/kb.py blueprint 6
   ```
2. **创建仿真题任务**（自动检索同年级真题母题并生成完整约束提示词）：
   ```bash
   python3 scripts/kb.py task <知识点id> <年级3-7> [难度1-3] [题数] [--qtype 题型]
   ```
   命令会输出提示词、母题列表（`[R1]`/`[B1]`/`[W1]`）以及结果输出路径 `work/out/<task_id>.json`。
3. **仿写真题并写出 JSON**：
   - 严格按照提示词中的年级词表、句长、语法、题型版式出题；
   - 每道题必须填写 `"mimic": "R1"`（对应本次给出的母题编号），保留母题考查方式但更换语境与词汇（相似度过高会被机检退回）；
   - 将 JSON 原样写入 `work/out/<task_id>.json`。
4. **盲解复核 + 机检入待审**：
   ```bash
   python3 scripts/kb.py blind work/out/<task_id>.json
   ```
   独立不看答案作答，将答案 JSON 写入 `work/out/<task_id>.blind.json`，然后执行：
   ```bash
   python3 scripts/kb.py ingest work/out/<task_id>.json --model codex
   ```
   - 若有题目未通过（超纲词、句长超限、与母题过像、盲解歧义），根据退回原因修改 `work/out/<task_id>.json` 并重新 `ingest`。
   - 通过的题目会自动写入 `data/待审题目/`，格式可直接并入 `data/questions/`。

## 也可使用 MCP 或 HTTP API

- **MCP 服务**（推荐给 Codex / WorkBuddy / Claude Code）：`python3 scripts/kb.py mcp`（工具：`list_topics`、`get_exemplars`、`get_blueprint`、`create_task`、`get_blind_prompt`、`ingest_questions`、`generate_questions`）。
- **HTTP API + 本地网页**：`python3 scripts/kb.py serve`（默认 `http://localhost:8765`，完整接口见 `docs/API.md`）。
- **一步调用外部 API 或本地 CLI**：`python3 scripts/kb.py generate <id> <年级> [难度] [题数] [--qtype 题型] [--provider codex|claude|openai|anthropic|cli]`。

## 新增语料库流程

如果用户提供了新的试卷目录（`.md` / `.txt` / `.docx` / 可提取文字的 `.pdf`）：
```bash
python3 scripts/kb.py import <试卷目录>
python3 scripts/kb.py items
python3 scripts/kb.py stats
python3 scripts/kb.py bundle
```
