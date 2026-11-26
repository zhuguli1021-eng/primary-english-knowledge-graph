#!/usr/bin/env python3
"""小学英语知识图谱 MCP 服务（stdio，仅标准库）。

供 Codex、WorkBuddy、CodeBuddy、Claude Code 等本地智能体直接调用，无需 API Key 即可完成：
  list_topics     → 查知识点、年级考频与真题考法
  get_exemplars   → 按知识点 + 年级 + 题型检索真题原题（母题）
  get_blueprint   → 查该年级真卷大题结构
  create_task     → 生成以「知识点 + 年级 + 语料库 + 真题母题」为核心的出题任务与提示词
  get_blind_prompt→ 生成盲解复核提示词（隐藏答案，让智能体独立重做）
  ingest_questions→ 校验题目（年级词表、句长、答案、mimic 真题母题相似度、盲解比对）并写入 data/待审题目/
  generate_questions → 若需后台调用已配置的 API/CLI 模型一步出题，也可直接调用
"""
import json, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import api, gen

TOOLS = [
    {
        'name': 'list_curriculum',
        'description': '按人教教材年级、上下册、单元、关键词或原考点编号查询单元学习要求及关联。结果保留待核位置。',
        'inputSchema': {'type': 'object', 'properties': {
            'grade': {'type': 'integer', 'minimum': 3, 'maximum': 9},
            'semester': {'type': 'string', 'enum': ['上', '下']},
            'unit': {'type': 'string'}, 'q': {'type': 'string'}, 'topic': {'type': 'string'},
        }},
    },
    {
        'name': 'list_cpp_units',
        'description': '查询 CPP（Cambridge Primary Path V2.1）单元目标卡映射标准（G0~G6 共 63 个单元），返回单元主题、核心词、语法目标及推荐双向细目表行（知识点 × 选择/填空/阅读/写作题量）。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'level': {'type': 'string', 'description': '级别 G0~G6'},
                'unit': {'type': 'string', 'description': '具体单元，如 G3-U1'},
            },
        },
    },
    {
        'name': 'draw_blueprint',
        'description': '按双向细目表（纵轴知识点 × 横轴选择/填空/阅读/写作）从语料库真题池优先抽题并附上真题来源，返回分板块题目与需要 AI 补齐的题量缺口（shortfalls）。',
        'inputSchema': {
            'type': 'object',
            'required': ['grade', 'rows'],
            'properties': {
                'grade': {'type': 'integer', 'description': '试卷年级 3~7'},
                'cpp_unit': {'type': 'string', 'description': '可选对标 CPP 单元，如 G3-U1'},
                'scores': {'type': 'object', 'description': '各题型单题分值，如 {"choice":2,"fill":2,"reading":2,"writing":10}'},
                'rows': {
                    'type': 'array',
                    'description': '双向细目表行，每项 {"topic":"vb.modal_can","choice":3,"fill":2,"reading":0,"writing":0}',
                    'items': {'type': 'object'},
                },
            },
        },
    },
    {
        'name': 'list_topics',
        'description': '查询小学英语知识点列表，包含指定年级的真题考频、推荐难度和常见题型。',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'grade': {'type': 'integer', 'description': '年级 3~7（7=小升初）'},
                'domain': {'type': 'string', 'description': '领域：语音/词汇/词法/时态/句法/交际/阅读/写作'},
                'q': {'type': 'string', 'description': '按关键词搜索知识点名称或 id'},
            },
        },
    },
    {
        'name': 'get_exemplars',
        'description': '从语料库真题题目库中，按知识点、年级、题型检索最该模仿的真题原题（母题）和该年级的考法分布。',
        'inputSchema': {
            'type': 'object',
            'required': ['topic', 'grade'],
            'properties': {
                'topic': {'type': 'string', 'description': '知识点 id，如 te.past_simple'},
                'grade': {'type': 'integer', 'description': '年级 3~7'},
                'qtype': {'type': 'string', 'description': '题型，如 单项选择/适当形式/句型转换/连词成句/完形填空/阅读理解/书面表达'},
                'k': {'type': 'integer', 'description': '返回真题数量，默认 6'},
                'seed': {'type': 'integer', 'description': '随机种子，换一批母题'},
            },
        },
    },
    {
        'name': 'get_blueprint',
        'description': '获取指定年级（3~7）真卷的大题结构蓝图（常见题型、出现比例、平均题数、顺序）。',
        'inputSchema': {
            'type': 'object',
            'properties': {'grade': {'type': 'integer', 'description': '年级 3~7，不填返回全部年级'}},
        },
    },
    {
        'name': 'create_task',
        'description': '创建一个仿真题出题任务：自动结合知识点、年级约束、语料库考频和检索到的真题母题生成提示词，并返回 task_id 和母题 refs。智能体按提示词出题后，再调用 ingest_questions 入库质检。',
        'inputSchema': {
            'type': 'object',
            'required': ['topic', 'grade'],
            'properties': {
                'topic': {'type': 'string', 'description': '知识点 id'},
                'grade': {'type': 'integer', 'description': '年级 3~7'},
                'difficulty': {'type': 'integer', 'description': '难度 1 基础 / 2 标准 / 3 提高，不填自动按年级推荐'},
                'n': {'type': 'integer', 'description': '出题数量，默认 5'},
                'qtype': {'type': 'string', 'description': '题型（可选，不填按该年级语料高频题型自动选）：' + '/'.join(gen.ALL_Q)},
                'seed': {'type': 'integer', 'description': '母题抽样种子'},
                'material': {'type': 'string', 'description': '可选阅读素材原文'},
            },
        },
    },
    {
        'name': 'get_blind_prompt',
        'description': '为已出的题目生成隐藏答案的盲解复核提示词，供智能体独立重做检查是否存在歧义或错答。',
        'inputSchema': {
            'type': 'object',
            'required': ['task_id'],
            'properties': {
                'task_id': {'type': 'string', 'description': 'create_task 返回的 task_id'},
                'reply': {'type': 'string', 'description': '已出的题目 JSON 字符串（若已写入 task.out 可省略）'},
            },
        },
    },
    {
        'name': 'ingest_questions',
        'description': '对智能体出好的题目做全套质检（年级词表、句长、答案唯一性、mimic 母题编号与防照抄相似度、可选盲解比对），通过的题写入 data/待审题目/。',
        'inputSchema': {
            'type': 'object',
            'required': ['task_id'],
            'properties': {
                'task_id': {'type': 'string', 'description': 'create_task 返回的 task_id'},
                'reply': {'type': 'string', 'description': '题目 JSON 字符串（数组或篇章/作文对象）；也可直接传 questions'},
                'questions': {'description': '已解析的题目 JSON（数组或对象）'},
                'blind': {'description': '可选盲解答案 JSON（数组或字符串）'},
                'model': {'type': 'string', 'description': '出题来源标记，如 codex / workbuddy'},
            },
        },
    },
    {
        'name': 'generate_questions',
        'description': '调用本机 llm.json 配置的大模型 API 或 CLI（codex/claude/cli）一步完成出题、盲解复核并写入待审目录。',
        'inputSchema': {
            'type': 'object',
            'required': ['topic', 'grade'],
            'properties': {
                'topic': {'type': 'string'},
                'grade': {'type': 'integer'},
                'difficulty': {'type': 'integer'},
                'n': {'type': 'integer'},
                'qtype': {'type': 'string'},
                'provider': {'type': 'string', 'description': 'openai / anthropic / codex / claude / cli'},
                'model': {'type': 'string'},
                'verify': {'type': 'boolean', 'description': '是否盲解复核，默认 true'},
            },
        },
    },
]

HANDLERS = {
    'list_cpp_units': api.get_cpp_units,
    'list_curriculum': api.get_curriculum,
    'draw_blueprint': api.post_draw_blueprint,
    'list_topics': api.get_topics,
    'get_exemplars': api.get_exemplars,
    'get_blueprint': api.get_blueprint,
    'create_task': api.post_task,
    'get_blind_prompt': api.post_blind,
    'ingest_questions': api.post_ingest,
    'generate_questions': api.post_generate,
}

def read_msg():
    line = sys.stdin.readline()
    if not line: return None
    if line.lower().startswith('content-length:'):
        n = int(line.split(':', 1)[1].strip())
        while True:
            h = sys.stdin.readline()
            if not h or h in ('\r\n', '\n'): break
        return json.loads(sys.stdin.read(n))
    line = line.strip()
    return json.loads(line) if line else read_msg()

def send_msg(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()

def serve_stdio():
    while True:
        try: msg = read_msg()
        except Exception: break
        if msg is None: break
        mid = msg.get('id'); method = msg.get('method', ''); params = msg.get('params') or {}
        if method == 'notifications/initialized' or mid is None: continue
        try:
            if method == 'initialize':
                res = {
                    'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'primary-english-kb', 'version': '2.0.0'},
                }
            elif method == 'ping':
                res = {}
            elif method == 'tools/list':
                res = {'tools': TOOLS}
            elif method == 'tools/call':
                name = params.get('name'); args = params.get('arguments') or {}
                if name not in HANDLERS: raise ValueError(f'未知工具：{name}')
                data = HANDLERS[name](**args)
                res = {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False, indent=1)}]}
            else:
                send_msg({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'Method not found: {method}'}})
                continue
            send_msg({'jsonrpc': '2.0', 'id': mid, 'result': res})
        except Exception as e:
            if method == 'tools/call':
                send_msg({'jsonrpc': '2.0', 'id': mid, 'result': {'isError': True, 'content': [{'type': 'text', 'text': str(e)}]}})
            else:
                send_msg({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32000, 'message': str(e)}})

if __name__ == '__main__':
    serve_stdio()
