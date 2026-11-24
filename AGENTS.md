# 小学英语知识图谱 · 智能体出题与教研规范（Codex / WorkBuddy / Claude Code）

本仓库所有出题**必须**同时围绕四个核心依据：
1. **知识点**（`data/topics.json`）：说明、掌握标准、常见错误
2. **年级**（`data/levels.json`）：词表分级、单句词数上限、已学语法（首学年级晚于学生年级的知识点不出）
3. **语料库**（`corpus/`、`data/corpus_index.json`、`data/exam_stats.json`）：分年级真卷考频与考法分布
4. **真题原题（母题）**（`data/exam_items.json`、`data/exam_blueprint.json`）：逐题仿写真题的考查角度、句子结构、设空位置与选项设计，**不得照抄**

> **禁止凭空出题。** 任何出题请求都必须先通过 `kb.py task`（或 MCP 工具 `create_task`）检索真题母题并锁定约束，出题后必须通过 `kb.py ingest`（或 MCP 工具 `ingest_questions`）做全套质检再写入 `data/待审题目/`。

## 四步标准组卷与 CPP 单元目标映射流程

本系统以 `/Users/ang/Documents/教学项目/CPP单元目标卡V2.1_AI资料`（已映射为 `data/cpp_units.json`，含 G0~G6 共 63 个单元）作为核心映射标准，严格遵循四步组卷流程：

1. **第一步 · 定蓝图（双向细目表）**：横轴为题型（选择 / 填空 / 阅读完形 / 书面表达）与分值，纵轴为知识点（可按 CPP 单元自动映射，也可按年级高频考点或自定义勾选）。
   ```bash
   python3 scripts/kb.py cpp G3-U1
   ```
2. **第二步 · 抽素材（严格优先抽语料真题 + 缺题 AI 仿写真题补齐）**：优先从结构化真题池 `data/real_pool.json`（3,652 道单题 + 110 篇阅读/完形组题 + 138 道真卷作文，共 483 个真卷来源）抽题并附上原始真题来源；仅在题量不足时，调用 `kb.py task ... --cpp-unit G3-U1` 依照真题母题生成 AI 初稿补齐。
3. **第三步 · 按板块拆开逐题把关**：分「选择题 / 填空运用 / 阅读与完形 / 书面表达」四个板块逐题审阅，错题或不满意题支持单题换真题或单题 AI 仿写重出。
4. **第四步 · 人工四维校验（AI 初稿人工确认才生效）**：逐题核对**答案准确性、题干是否有歧义、是否超出年级/CPP 单元词表、卷内题与题是否重复**；所有 AI 生成题默认状态为 `draft`（初稿），必须经人工确认（`approved`）后才能进入第五步正式打印试卷。

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
