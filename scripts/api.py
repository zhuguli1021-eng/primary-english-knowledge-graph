#!/usr/bin/env python3
"""统一出题与组卷接口层：HTTP API（kb.py serve）和 MCP 服务（scripts/mcp_server.py）共用。"""
import json, pathlib, random
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

def get_curriculum(grade=None, semester=None, unit=None, q=None, topic=None):
    from curriculum import select
    return select(load('curriculum.json'), grade, semester, unit, q, topic)

def get_cpp_units(level=None, unit=None):
    if not (D / 'cpp_units.json').exists():
        import cpp_map; cpp_map.build_cpp()
    c = load('cpp_units.json')
    units = c.get('units', [])
    if level: units = [u for u in units if u['level'].upper() == str(level).upper()]
    if unit:
        uid = str(unit).upper().replace('|', '-')
        units = [u for u in units if u['id'] == uid]
    return {'version': c.get('version'), 'levels': c.get('levels', []), 'count': len(units), 'units': units}

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

def post_draw_blueprint(grade, rows, scores=None, cpp_unit='', seed=None):
    """第二步·抽素材：按双向细目表（rows=[{topic, choice, fill, reading, writing}]）严格优先抽真题池并附真题来源，返回分板块题目与缺口。"""
    g = _int(grade, 6)
    rnd = random.Random(_int(seed))
    rp = load('real_pool.json') if (D / 'real_pool.json').exists() else {'sources': [], 'singles': [], 'groups': [], 'writings': []}
    curated = load('questions.json') if (D / 'questions.json').exists() else []
    srcs = rp.get('sources', [])
    scores = scores or {'choice': 2, 'fill': 2, 'reading': 2, 'writing': 10}
    used_ids = set()
    sections = {'choice': [], 'fill': [], 'reading': [], 'writing': []}
    shortfalls = []

    def rank_grade(qg):
        return 3 if qg == g else 2 if qg == g - 1 else 1 if (qg <= g + 1) else 0

    for row in rows or []:
        tid = row['topic']
        # 1. 选择 & 填空
        for sec_key in ('choice', 'fill'):
            need = _int(row.get(sec_key), 0)
            if need <= 0: continue
            cands = []
            for s in rp.get('singles', []):
                if s['id'] in used_ids or s['type'] != sec_key or tid not in s.get('topics', [s['topic']]): continue
                rg = rank_grade(s['grade'])
                if not rg: continue
                score = 100 + rg * 10 + (4 if s.get('answerVerified') else 0) + (5 if s['topic'] == tid else 0) + rnd.random()
                cands.append((score, s, True))
            for q in curated:
                if q['id'] in used_ids or q.get('passage') or q['type'] != sec_key or q['topic'] != tid: continue
                rg = rank_grade(q['grade'])
                if not rg: continue
                cands.append((rg * 8 + 3 + rnd.random(), q, False))
            cands.sort(key=lambda x: -x[0])
            got = 0
            for _, item, is_real in cands:
                if got >= need: break
                used_ids.add(item['id'])
                q_out = dict(item, topic=tid)
                if is_real:
                    q_out.update(origin='real', status='verified' if item.get('answerVerified') else 'needs_check',
                                 examSrc=srcs[item['si']], explain=item.get('explain', ''), score=scores.get(sec_key, 2))
                else:
                    q_out.update(origin='curated', status='verified', examSrc='正式精编题库（已审）', score=scores.get(sec_key, 2))
                sections[sec_key].append(q_out)
                got += 1
            if got < need:
                shortfalls.append({'section': sec_key, 'topic': tid, 'needed': need - got, 'grade': g, 'cppUnit': cpp_unit})

        # 2. 阅读 / 完形篇章
        need_r = _int(row.get('reading'), 0)
        if need_r > 0:
            want_cloze = tid == 'rd.cloze'
            gcands = []
            for gr in rp.get('groups', []):
                if gr['id'] in used_ids: continue
                if want_cloze != (gr['qtype'] == '完形填空'): continue
                rg = rank_grade(gr['grade'])
                if not rg: continue
                gcands.append((100 + rg * 10 + sum(1 for x in gr['questions'] if x.get('answerVerified')) + rnd.random(), gr, True))
            # curated groups
            by_p = {}
            for q in curated:
                if q.get('passage') and (q['topic'] == 'rd.cloze') == want_cloze:
                    by_p.setdefault(q['passage'], []).append(q)
            for p_txt, p_qs in by_p.items():
                pid = 'CP-' + p_qs[0]['id']
                if pid in used_ids: continue
                rg = rank_grade(p_qs[0]['grade'])
                if rg: gcands.append((rg * 9 + 5 + rnd.random(), {'id': pid, 'passage': p_txt, 'questions': p_qs, 'title': p_qs[0].get('title', '')}, False))
            gcands.sort(key=lambda x: -x[0])
            got_r = 0
            for _, gr, is_real in gcands:
                if got_r >= need_r: break
                used_ids.add(gr['id'])
                for q in gr['questions']:
                    q_out = dict(q)
                    if is_real:
                        q_out.update(id=f"{gr['id']}-{len(sections['reading'])+1}", grade=gr['grade'], passage=gr['passage'],
                                     origin='real', status='verified' if q.get('answerVerified') else 'needs_check',
                                     examSrc=srcs[gr['si']], explain='', score=scores.get('reading', 2))
                    else:
                        q_out.update(origin='curated', status='verified', examSrc=q.get('source') or '正式精编题库（已审）', score=scores.get('reading', 2))
                    sections['reading'].append(q_out)
                    got_r += 1
            if got_r < need_r:
                shortfalls.append({'section': 'reading', 'topic': tid, 'needed': need_r - got_r, 'grade': g, 'cppUnit': cpp_unit})

        # 3. 书面表达
        need_w = _int(row.get('writing'), 0)
        if need_w > 0:
            wcands = []
            for w in rp.get('writings', []):
                if w['id'] in used_ids: continue
                rg = rank_grade(w['grade'])
                if not rg: continue
                wcands.append((100 + rg * 10 + (5 if w['topic'] == tid else 0) + rnd.random(), w, True))
            for q in curated:
                if q['id'] in used_ids or q['type'] != 'writing': continue
                rg = rank_grade(q['grade'])
                if rg: wcands.append((rg * 9 + (5 if q['topic'] == tid else 0) + rnd.random(), q, False))
            wcands.sort(key=lambda x: -x[0])
            got_w = 0
            for _, w, is_real in wcands:
                if got_w >= need_w: break
                used_ids.add(w['id'])
                w_out = dict(w)
                if is_real:
                    w_out.update(origin='real', status='verified', examSrc=srcs[w['si']], sample=w.get('sample', ''),
                                 require=w.get('require', f'不少于 {w.get("minWords", 60)} 词'), score=scores.get('writing', 10))
                else:
                    w_out.update(origin='curated', status='verified', examSrc='正式精编题库（含范文）', score=scores.get('writing', 10))
                sections['writing'].append(w_out)
                got_w += 1
            if got_w < need_w:
                shortfalls.append({'section': 'writing', 'topic': tid, 'needed': need_w - got_w, 'grade': g, 'cppUnit': cpp_unit})

    return {'grade': g, 'cppUnit': cpp_unit, 'sections': sections, 'shortfalls': shortfalls}

def post_task(topic, grade, difficulty=None, n=5, qtype=None, seed=None, material='', cpp_unit=''):
    t = gen.new_task(topic, _int(grade), _int(difficulty), _int(n, 5), qtype or None, _int(seed), material or '', cpp_unit or '')
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

def post_generate(topic, grade, difficulty=None, n=5, qtype=None, provider=None, model=None, verify=True, seed=None, material='', cpp_unit=''):
    return gen.generate(topic, _int(grade), _int(difficulty), _int(n, 5), qtype or None,
                        verify=_bool(verify, True), provider=provider or None, model=model or None,
                        seed=_int(seed), material=material or '', cpp_unit=cpp_unit or '')

GET = {
    'topics': get_topics,
    'curriculum': get_curriculum,
    'cpp-units': get_cpp_units,
    'exemplars': get_exemplars,
    'blueprint': get_blueprint,
    'select': get_select,
}
POST = {
    'draw-blueprint': post_draw_blueprint,
    'task': post_task,
    'blind': post_blind,
    'ingest': post_ingest,
    'generate': post_generate,
}
