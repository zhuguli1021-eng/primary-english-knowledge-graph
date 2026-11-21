#!/usr/bin/env python3
"""统一出题接口层：HTTP API（kb.py serve）和 MCP 服务（scripts/mcp_server.py）共用。"""
import json, pathlib
from kb import ROOT, D, load, rec_difficulty, grade_rate, select as kb_select
import corpus as C, gen

def _int(v, default=None):
    return default if v is None or v == '' else int(v)

def _bool(v, default=False):
    if v is None or v == '': return default
    if isinstance(v, bool): return v
    return str(v).lower() in ('1', 'true', 'yes', 'on')

def get_topics(grade=None, domain=None, q=None):
    topics = load('topics.json')
    st = load('exam_stats.json')['topics'] if (D / 'exam_stats.json').exists() else {}
    g = _int(grade)
    out = []
    for t in topics:
        if domain and t['domain'] != domain: continue
        if q and q.lower() not in (t['id'] + t['name'] + t['desc']).lower(): continue
        if g is not None and t['grade'] > g: continue
        s = st.get(t['id'], {})
        row = {
            'id': t['id'], 'name': t['name'], 'domain': t['domain'], 'sub': t['sub'],
            'grade': t['grade'], 'tier': s.get('tier', 1),
            'paperRate': grade_rate(st, t['id'], g) if g is not None else s.get('paperRate', 0),
        }
        if g is not None:
            row['recDifficulty'] = rec_difficulty(g, t['grade'])
            row['formats'] = (s.get('formats') or {}).get(str(g), {})
        out.append(row)
    out.sort(key=lambda x: (-x['paperRate'], x['grade'], x['id']))
    return {'count': len(out), 'grade': g, 'topics': out}

def get_exemplars(topic, grade, qtype=None, k=6, seed=None):
    g = _int(grade)
    if g not in (3, 4, 5, 6, 7): raise ValueError('grade 必须是 3~7')
    k = _int(k, 6); seed = _int(seed)
    qtype = qtype or None
    if qtype in gen.PASSAGE_Q + gen.WRITING_Q:
        blocks = C.exemplar_blocks(qtype, g, topic, k=min(k, 5), seed=seed)
        return {'topic': topic, 'grade': g, 'qtype': qtype, 'blocks': blocks}
    items = C.exemplars(topic, g, qtype, k=k, seed=seed)
    prof = C.format_profile(topic, g)
    return {
        'topic': topic, 'grade': g, 'qtype': qtype,
        'formatProfile': [{'qtype': q, 'count': c} for q, c in prof[:8]],
        'optionCount': C.option_count(items),
        'exemplars': [gen._slim(e) for e in items],
    }

def get_blueprint(grade=None):
    bp = load('exam_blueprint.json') if (D / 'exam_blueprint.json').exists() else {}
    if grade is not None and str(grade) != '':
        g = str(_int(grade))
        if g not in bp: raise ValueError(f'没有 {g} 年级的真卷蓝图')
        return {'grade': int(g), **bp[g]}
    return {'grades': bp}

def get_select(grade, n=20, seed=None):
    g = _int(grade); n = _int(n, 20); seed = _int(seed)
    if g not in (3, 4, 5, 6, 7): raise ValueError('grade 必须是 3~7')
    qs = kb_select(g, n, seed)
    return {'grade': g, 'count': len(qs), 'questions': qs}

def post_task(topic, grade, difficulty=None, n=5, qtype=None, seed=None, material=''):
    t = gen.new_task(topic, _int(grade), _int(difficulty), _int(n, 5), qtype or None, _int(seed), material or '')
    return {
        'task_id': t['id'],
        'out': t['out'],
        'params': t['params'],
        'optionCount': t.get('optionCount'),
        'refs': t['refs'],
        'prompt': t['prompt'],
    }

def post_blind(task_id, reply=None, questions=None):
    task = gen.load_task(task_id)
    if reply is None and questions is None:
        out_f = ROOT / task['out']
        if not out_f.exists(): raise ValueError(f'请提供 reply/questions，或先把题目写入 {task["out"]}')
        reply = out_f.read_text()
    v = gen.parse_reply(reply) if isinstance(reply, str) else (questions if questions is not None else reply)
    qs = gen.normalize(v, task)
    return {'task_id': task['id'], 'count': len(qs), 'prompt': gen.blind_prompt(qs, task['params']['grade'])}

def post_ingest(task_id, reply=None, questions=None, blind=None, model='API', verify=False):
    task = gen.load_task(task_id)
    if reply is None and questions is None:
        out_f = ROOT / task['out']
        if not out_f.exists(): raise ValueError(f'找不到 {task["out"]}，也没有传入 reply/questions')
        reply = out_f.read_text()
    if blind is None:
        bf = ROOT / (task['out'][:-5] + '.blind.json')
        if bf.exists(): blind = gen.parse_reply(bf.read_text())
    elif isinstance(blind, str):
        blind = gen.parse_reply(blind)
    payload = questions if questions is not None else reply
    cfg = gen.llm_config() if _bool(verify) and blind is None else None
    return gen.ingest(payload, task, blind_answers=blind, cfg=cfg, verify=_bool(verify), model=model or 'API')

def post_generate(topic, grade, difficulty=None, n=5, qtype=None, provider=None, model=None, verify=True, seed=None, material=''):
    return gen.generate(topic, _int(grade), _int(difficulty), _int(n, 5), qtype or None,
                        verify=_bool(verify, True), provider=provider or None, model=model or None,
                        seed=_int(seed), material=material or '')

GET = {
    'topics': get_topics,
    'exemplars': get_exemplars,
    'blueprint': get_blueprint,
    'select': get_select,
}
POST = {
    'task': post_task,
    'blind': post_blind,
    'ingest': post_ingest,
    'generate': post_generate,
}
