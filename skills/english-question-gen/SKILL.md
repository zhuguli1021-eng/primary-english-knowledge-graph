---
name: english-question-gen
description: |
  小学英语真题仿真自动出题技能（围绕知识点、年级、语料库、真题母题四核心）。
  当用户要求出小学英语练习题、模拟卷、小升初分班卷、单项选择、适当形式填空、句型转换、连词成句、完形填空、阅读理解、书面表达，或要求导入新试卷语料库时触发。
  触发词：小学英语出题、仿真题出题、按知识点出题、小升初出题、生成英语试卷、仿写真题、导入英语语料库、english-question-gen。
description_zh: 小学英语仿真题自动出题（知识点 + 年级 + 语料库 + 真题母题 + 盲解机检）
description_en: Primary English real-exam-grounded question generation with corpus exemplars and blind verification
version: 1.0.0
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# 小学英语仿真题自动出题（english-question-gen）

本技能驱动 `primary-english-knowledge-graph` 仓库完成**严格围绕知识点、年级、语料库、真题母题**的自动出题，无需外部 API Key，直接由当前本地智能体（Codex / WorkBuddy / CodeBuddy / Claude Code）完成出题与盲解复核，并保留完整 HTTP API 与 MCP 接口。

## 前提：定位项目目录

先确认当前工作目录是否包含 `scripts/kb.py` 与 `data/exam_items.json`；若不在项目根目录，请先 `cd` 到 `primary-english-knowledge-graph` 仓库目录。

## 核心铁律

1. **禁止凭空编题**：每次出题必须先运行 `kb.py task`（或调用 MCP `create_task`），让系统按「知识点 + 年级 + 语料库考频」从 10,000+ 道真题中检索出同年级真题母题。
2. **必须逐题仿写真题**：每题必须标注 `mimic`（如 `"R1"` / `"B1"` / `"W1"`），保留母题的考查角度、句子结构、设空位置和选项数量，更换语境和词汇，不能照抄。
3. **必须经过机检与盲解复核**：所有题目必须通过 `kb.py ingest`（校验年级词表、单句词数、答案唯一性、母题相似度防照抄、盲解一致性）才能写入 `data/待审题目/`。

## 操作步骤

### 单知识点出题
1. 查知识点与该年级常见题型：
   ```bash
   python3 scripts/kb.py topics --grade <3-7> --q <关键词>
   ```
2. 创建出题任务（获取母题与完整约束）：
   ```bash
   python3 scripts/kb.py task <知识点id> <年级3-7> [难度1-3] [题数] [--qtype 题型]
   ```
   支持的题型：`单项选择`、`情景交际`、`补全对话`、`语音辨音`、`不同类`、`适当形式`、`首字母填空`、`汉语提示填词`、`选词填空`、`句型转换`、`连词成句`、`翻译`、`完形填空`、`阅读理解`、`语篇填空`、`任务型阅读`、`书面表达`。不填 `--qtype` 时自动选用该知识点在该年级语料中最高频的题型。
3. 按输出提示词仿写题目，写入 `work/out/<task_id>.json`。
4. 生成盲解复核题面并独立作答（不看原答案），答案写入 `work/out/<task_id>.blind.json`：
   ```bash
   python3 scripts/kb.py blind work/out/<task_id>.json
   ```
5. 质检并写入 `data/待审题目/`：
   ```bash
   python3 scripts/kb.py ingest work/out/<task_id>.json --model workbuddy
   ```
   若报告中有未通过的题目，按错误原因修正后重跑 `ingest`，直到全部通过。

### 按真卷结构出一整套卷子
1. 查看该年级真卷蓝图：
   ```bash
   python3 scripts/kb.py blueprint <年级3-7>
   ```
2. 按蓝图中的大题顺序与高频知识点（`kb.py topics --grade <G>`），逐个大题执行 `task` → 仿写 → `blind` → `ingest`。
3. 汇总生成后的各文件路径与通过率汇报给用户。

### 正式入库（用户确认待审题目后）
用户审阅 `data/待审题目/` 并将其移入 `data/questions/` 后，执行：
```bash
python3 scripts/kb.py questions && python3 scripts/kb.py check && python3 scripts/kb.py bundle
```
