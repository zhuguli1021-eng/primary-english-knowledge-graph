#!/usr/bin/env python3
"""小学英语知识库工具（仅标准库）。

  python3 scripts/kb.py import <目录>          把新试卷文字版（.md/.txt/.docx/.pdf）导入 corpus/ 并更新索引
  python3 scripts/kb.py items                  把 corpus/ 拆成真题题目库（data/exam_items.json）与年级真卷蓝图
  python3 scripts/kb.py stats  [语料目录]      统计分年级真题考频、考法分布与共考关联 → data/exam_stats.json
  python3 scripts/kb.py topics [--grade G]     列出知识点及该年级考频、常见题型
  python3 scripts/kb.py exemplars <id> <年级> [--qtype 题型]  查看该知识点在该年级的真题母题
  python3 scripts/kb.py blueprint [年级]       查看各年级真卷大题结构蓝图
  python3 scripts/kb.py prompt <id> <年级> [难度] [题数] [--qtype 题型]   生成围绕真题母题的出题提示词
  python3 scripts/kb.py task   <id> <年级> [难度] [题数] [--qtype 题型]   为 Codex/WorkBuddy 等本地智能体创建出题任务
  python3 scripts/kb.py blind  <任务或结果文件>                           生成盲解复核提示词
  python3 scripts/kb.py ingest <结果文件> [--blind 文件] [--model 来源]   机检 + 真题依据检查 + 盲解比对 → data/待审题目/
  python3 scripts/kb.py generate <id> <年级> [难度] [题数] [--qtype 题型] [--provider codex|claude|openai|anthropic|cli]
  python3 scripts/kb.py serve [端口]           启动本地网页 + HTTP API（http://localhost:8765）
  python3 scripts/kb.py mcp                    启动 stdio MCP 服务（供 Codex / WorkBuddy / Claude Code 调用）
  python3 scripts/kb.py questions              把 data/questions/*.txt 编译成 data/questions.json
  python3 scripts/kb.py check                  校验知识点、先修边、题库（词汇超纲、句长、答案、重复）
  python3 scripts/kb.py select <年级> [题数]   按该年级真题考频加权抽一套题
  python3 scripts/kb.py bundle                 打包成 app/data.js 与 app/publish.html 供网页使用
"""
import json, re, sys, os, collections, pathlib, random, functools, datetime, urllib.request, http.server

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / 'data'
load = lambda name: json.loads((D / name).read_text())

# ---------- 词汇分级 ----------
@functools.lru_cache(None)
def bands():
    lv = load('levels.json'); wl = load('wordlists.json')
    g34 = set(lv['grade34'].lower().split())
    l2 = set(wl['level2']) | g34 | set(lv['pep_extra'].lower().split())
    l3 = l2 | set(wl['level3'])
    irr = {}
    for base, forms in wl['irregular'].items():
        for f in forms:
            irr[f] = base
    irr.update({'better': 'good', 'best': 'good', 'worse': 'bad', 'worst': 'bad', 'more': 'many', 'most': 'many',
                'less': 'little', 'least': 'little', 'children': 'child', 'men': 'man', 'women': 'woman', 'feet': 'foot',
                'teeth': 'tooth', 'mice': 'mouse', 'am': 'be', 'is': 'be', 'are': 'be', 'was': 'be', 'were': 'be',
                'has': 'have', 'had': 'have', 'does': 'do', 'did': 'do', 'went': 'go', 'mine': 'my', 'yours': 'your',
                'hers': 'her', 'ours': 'our', 'theirs': 'their', 'myself': 'my', 'himself': 'him', 'herself': 'her',
                'themselves': 'them', 'yourself': 'your', 'ourselves': 'our', 'itself': 'it', 'yourselves': 'your'})
    return {3: g34, 4: g34, 5: l2, 6: l2, 7: l3}, irr

FUNCTION = set("a an the and or but so because if when than then as to of in on at by for with from about into up down out off over after before not no yes".split())

def candidates(w, irr):
    yield w
    if w in irr: yield irr[w]
    if w.startswith('un') and len(w) > 4: yield from candidates(w[2:], irr)
    for suf, rep in (('ies', 'y'), ('ied', 'y'), ('ier', 'y'), ('iest', 'y'), ('ily', 'y'), ('es', ''), ('s', ''),
                     ('ed', ''), ('ed', 'e'), ('d', ''), ('ing', ''), ('ing', 'e'), ('er', ''), ('er', 'e'),
                     ('est', ''), ('est', 'e'), ('ly', ''), ('ly', 'le'), ('ves', 'f'), ('ves', 'fe'), ('th', ''),
                     ('iness', 'y'), ('ness', ''), ('ful', ''), ('less', ''), ('ies', 'ie')):
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            stem = w[:-len(suf)] + rep
            yield stem
            if len(stem) > 2 and stem[-1] == stem[-2]:      # swimming → swim, bigger → big
                yield stem[:-1]
            if stem in irr: yield irr[stem]

def out_of_band(text, grade, B, irr):
    """返回超出该年级词表的单词。不算：带中文注释的词、题干引号里的目标词、人名地名（大写且不在任何词表里）。"""
    text = re.sub(r"[A-Za-z' -]+\s*[（(][^)）]*[\u4e00-\u9fff][^)）]*[)）]", ' ', text)   # 带注释的生词
    text = re.sub(r'\d+(st|nd|rd|th)\b', ' ', text)
    allowed, every = B[grade], B[7]
    bad = []
    for m in re.finditer(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text):
        tok = m.group(0); w = tok.lower()
        if w.endswith("n't"):
            w = {"can't": 'can', "won't": 'will', "shan't": 'shall'}.get(w, w[:-3])
        w = re.sub(r"'(s|re|m|ve|ll|d)$", '', w)
        if len(w) <= 1 or w in FUNCTION: continue
        ok = lambda ws: any(c in ws for c in candidates(w, irr)) or all(any(c in ws for c in candidates(x, irr)) for x in w.split('-'))
        if ok(allowed): continue
        if tok[0].isupper() and not ok(every): continue      # 专有名词
        bad.append(tok)
    return bad

# ---------- 真题统计 ----------
ITEM = re.compile(r'_{2,}|^\s*[(（]\s*[)）]?\s*\d|^\s*\)?\s*\d{1,2}\s*[.．、]|[(（]\s+[)）]')
OPT = re.compile(r'\b[A-D][.．]\s*([^A-D]+?)(?=\s+[A-D][.．]|$)')
WORDSETS = [  # 选项全部落在某个词集里 → 这道题考的就是这个点
    ('ar.a_an', {'a', 'an', '/'}), ('ar.zero', {'a', 'an', 'the', '/'}),
    ('pr.personal', {'i', 'me', 'he', 'him', 'she', 'her', 'we', 'us', 'they', 'them', 'you', 'it'}),
    ('pr.possessive_pron', {'my', 'mine', 'your', 'yours', 'his', 'her', 'hers', 'our', 'ours', 'their', 'theirs', 'its'}),
    ('pr.reflexive', {'myself', 'yourself', 'himself', 'herself', 'ourselves', 'themselves', 'yourselves', 'itself', 'me', 'him', 'her', 'them', 'us'}),
    ('pr.demonstrative', {'this', 'that', 'these', 'those', 'it'}),
    ('pr.indefinite', {'other', 'others', 'another', 'the other', 'the others', 'both', 'all', 'either', 'neither', 'none', 'some', 'any', 'something', 'anything', 'nothing', 'everything', 'someone', 'anyone', 'nobody', 'everyone'}),
    ('nn.quantity', {'some', 'any', 'many', 'much', 'a lot of', 'a few', 'a little', 'few', 'little', 'lots of'}),
    ('pp.time', {'in', 'on', 'at', 'for', 'since', 'during'}),
    ('pp.place', {'in', 'on', 'under', 'behind', 'next to', 'near', 'between', 'beside', 'in front of', 'over', 'above', 'across', 'through'}),
    ('pp.common', {'by', 'with', 'for', 'of', 'from', 'about', 'to', 'in', 'on', 'at', 'like', 'without'}),
    ('sy.conjunctions', {'and', 'but', 'or', 'so', 'because', 'if', 'when', 'until', 'though', 'although', 'before', 'after', 'while', 'than'}),
    ('sy.how_phrases', {'how many', 'how much', 'how old', 'how often', 'how long', 'how far', 'how soon', 'how', 'how about', 'how tall', 'how heavy'}),
    ('sy.wh_questions', {'what', 'where', 'when', 'who', 'whose', 'which', 'why', 'how', 'what time', 'what colour', 'what color', 'what day', 'who\'s'}),
    ('vb.modal_must', {'can', 'could', 'must', 'mustn\'t', 'should', 'may', 'need', 'needn\'t', 'have to', 'has to', 'can\'t', 'shouldn\'t', 'might', 'will'}),
    ('vb.be', {'am', 'is', 'are', 'be', 'was', 'were'}),
    ('ph.letters', set('abcdefghijklmnopqrstuvwxyz')),
]
GENERIC = {'rd.detail', 'vb.past_form', 'sy.conjunctions', 'vb.third_person', 'pp.common', 'pr.possessive_adj'}  # 信号太宽，不参与共考

def option_topic(line, irr):
    """把一行 A./B./C. 选项归到一个被考知识点；同一词根的不同形式 → 动词形式/比较级/复数。"""
    opts = [re.sub(r'[.。]$', '', o.strip().lower()) for o in OPT.findall(line)]
    if len(opts) < 3 or any(len(o) > 30 for o in opts): return None
    for tid, ws in WORDSETS:
        if all(o in ws for o in opts): return tid
    roots = {min(candidates(o.split()[-1], irr), key=len) for o in opts if o}
    if len(roots) == 1 and len(opts) >= 3:
        if any(o.endswith(('er', 'est')) or o.startswith(('more ', 'most ')) for o in opts): return 'ad.comparative_form'
        if any(o.endswith('ing') or o.startswith('to ') for o in opts): return 'vb.nonfinite'
        if any(o.split()[-1] in irr or o.endswith('ed') for o in opts): return 'te.tense_choice'
        return 'vb.verb_forms'
    return None

def stats(corpus=None):
    """按 data/corpus_index.json 登记的卷子统计（不含答案卷）；每个知识点给出总体考频和分年级考频。"""
    topics = load('topics.json')
    croot = pathlib.Path(corpus) if corpus else ROOT / 'corpus'
    index = json.loads((D / 'corpus_index.json').read_text()) if (D / 'corpus_index.json').exists() else \
        [{'file': p.name, 'grade': 7, 'kind': '真题'} for p in sorted(croot.glob('*.txt'))]
    index = [x for x in index if x['kind'] != '答案' and (croot / x['file']).exists()]
    papers = [croot / x['file'] for x in index]; pgrade = {str(croot / x['file']): x['grade'] for x in index}
    by_grade = collections.defaultdict(collections.Counter); n_grade = collections.Counter(x['grade'] for x in index)
    sig = {t['id']: [re.compile(s, re.I | re.M) for s in t['signals']] for t in topics}
    zh = {t['id']: [bool(re.search(r'[一-鿿]', s)) for s in t['signals']] for t in topics}
    _, irr = bands()
    per_paper = collections.Counter(); hits = collections.Counter(); ex = collections.defaultdict(list)
    opt_hits = collections.Counter(); co = collections.Counter(); stem = (None, [])
    for p in papers:
        seen = set()
        src = p.stem.replace('ocr_', '扫描:') if p.parent == croot else f'{p.parent.name}·{p.stem}'
        for line in p.read_text(errors='ignore').split('\n'):
            line = line.strip()
            if not line: continue
            ot = option_topic(line, irr)
            if ot:   # 选项行：确定这道题考的点，并与题干里出现的其他点建立“共考”关联
                opt_hits[ot] += 1; seen.add(ot)
                if stem[0] and len(ex[ot]) < 6 and 20 < len(stem[0]) < 160:
                    ex[ot].append({'text': stem[0] + '  ' + line, 'src': src})
                for t in stem[1]:
                    if t != ot: co[tuple(sorted((t, ot)))] += 1
                stem = (None, [])
                continue
            is_item = bool(ITEM.search(line))
            got = []
            for tid, rs in sig.items():
                if any((is_item or z) and r.search(line) for r, z in zip(rs, zh[tid])):
                    got.append(tid)
            for tid in got:
                hits[tid] += 1; seen.add(tid)
                needs_blank = not tid.startswith(('rd.', 'wr.', 'fn.'))       # 语法点只收带空格的题作例句
                if is_item and len(ex[tid]) < 6 and 20 < len(line) < 160 and re.search('[A-Za-z]{3}', line) and ('_' in line or not needs_blank):
                    ex[tid].append({'text': line, 'src': src})
            if is_item and '_' in line:
                stem = (line, [t for t in got if not all(zh[t]) and t not in GENERIC])
        per_paper.update(seen); by_grade[pgrade[str(p)]].update(seen)
    n = len(papers)
    out = {'papers': n, 'papersByGrade': {str(g): c for g, c in sorted(n_grade.items())},
           'note': '按语料库每份卷子（扫描件按每4页计一份）是否出现该知识点的信号统计；信号是关键词/正则，结果是近似值。byGrade 是分年级考频，formats 是该年级真题里的考法分布。',
           'topics': {}, 'related': []}
    try:
        import corpus as C; has_items = (D / 'exam_items.json').exists()
    except Exception: has_items = False
    for t in topics:
        r = per_paper[t['id']] / n
        bg = {str(g): {'rate': round(by_grade[g][t['id']] / n_grade[g], 3), 'papers': n_grade[g]} for g in sorted(n_grade)}
        rec = {'paperRate': round(r, 3), 'hits': hits[t['id']], 'optionHits': opt_hits[t['id']],
               'tier': 3 if r >= .5 else 2 if r >= .2 else 1, 'byGrade': bg, 'examples': ex[t['id']]}
        if has_items:
            rec['formats'] = {str(g): dict(C.format_profile(t['id'], g)[:6]) for g in range(max(3, t['grade']), 8)}
            best = [e for g in (7, 6, 5, 4, 3) if g >= t['grade'] for e in C.exemplars(t['id'], g, k=2)][:6]
            if best: rec['examples'] = [{'text': e['text'].replace('\n', '  '), 'src': e.get('tag') or e['src'], 'grade': e['grade']} for e in best]
        out['topics'][t['id']] = rec
    edges = {tuple(sorted((d['topicId'], d['prerequisiteId']))) for d in load('dependencies.json')}
    total = sum(co.values()) or 1
    ta = collections.Counter(); [ta.update({a: c, b: c}) for (a, b), c in co.items()]
    for (a, b), c in co.most_common():
        lift = c * total * 2 / (ta[a] * ta[b])
        if c >= 5 and lift >= 1.2 and (a, b) not in edges:
            out['related'].append({'a': a, 'b': b, 'count': c, 'lift': round(lift, 2),
                                   'reason': f'真题中 {c} 道单选题：选项考「{a}」时题干同时涉及「{b}」' if opt_hits[a] else f'真题中 {c} 道题同时考这两个点'})
    out['related'] = out['related'][:60]
    (D / 'exam_stats.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    tiers = collections.Counter(v['tier'] for v in out['topics'].values())
    print(f'{n} 份真卷；必考 {tiers[3]}、常考 {tiers[2]}、偶考 {tiers[1]}；自动关联 {len(out["related"])} 条')
    for t in sorted(topics, key=lambda t: -out['topics'][t['id']]['paperRate'])[:25]:
        print(f"  {out['topics'][t['id']]['paperRate']:.0%}  {t['name']}")

# ---------- 校验 ----------
def check():
    topics = load('topics.json'); deps = load('dependencies.json'); lv = load('levels.json')
    T = {t['id']: t for t in topics}; errs = []
    if len(T) != len(topics): errs.append('知识点 id 重复')
    for d in deps:
        for k in ('topicId', 'prerequisiteId'):
            if d[k] not in T: errs.append(f'边引用了不存在的知识点 {d[k]}')
        if d['topicId'] in T and d['prerequisiteId'] in T and d['strength'] == 'hard' \
                and T[d['prerequisiteId']]['grade'] > T[d['topicId']]['grade']:
            errs.append(f"硬先修晚于本点：{d['prerequisiteId']} → {d['topicId']}")
    g = collections.defaultdict(list)
    for d in deps: g[d['topicId']].append(d['prerequisiteId'])
    state = {}
    def dfs(u, path):
        state[u] = 1
        for v in g[u]:
            if state.get(v) == 1: errs.append('先修环：' + ' → '.join(path + [v]))
            elif not state.get(v): dfs(v, path + [v])
        state[u] = 2
    for t in T: state.get(t) or dfs(t, [t])
    for t in topics:
        for s in t['signals']: re.compile(s)
    qs = load('questions.json') if (D / 'questions.json').exists() else []
    seen = {}; warn = 0
    for q in qs:
        e, w = check_one(q, T, lv)
        errs += [f"{q['id']}: {x}" for x in e]
        for x in w: warn += 1; print(f"  ⚠ {q['id']}（{q['grade']}年级）{x}")
        key = re.sub(r'\W+', '', (q['stem'] + str(q.get('choices', ''))).lower())
        if key in seen and not q.get('passage'): errs.append(f"{q['id']}: 与 {seen[key]} 题干重复")
        seen[key] = q['id']
    cover = collections.Counter(q['topic'] for q in qs)
    empty = [t['id'] for t in topics if not cover[t['id']]]
    print(f'知识点 {len(topics)}，先修边 {len(deps)}，题目 {len(qs)}；错误 {len(errs)}，提醒 {warn}；无题知识点 {len(empty)}')
    for e in errs: print('  ✗', e)
    if empty: print('  无题：', ', '.join(empty))
    return not errs

def check_one(q, T, lv):
    """单题质检，返回 (错误, 提醒)。题库校验和 AI 出题共用。"""
    B, irr = bands(); errs, warns = [], []
    t = T.get(q.get('topic'))
    if not t: return [f"知识点不存在 {q.get('topic')}"], []
    if q.get('grade') not in (3, 4, 5, 6, 7): return ['年级必须是 3~7'], []
    if q['grade'] < t['grade']: errs.append(f"题目年级 {q['grade']} 早于知识点首学年级 {t['grade']}")
    if q.get('difficulty') not in (1, 2, 3): errs.append('难度必须是 1~3')
    if not q.get('stem'): return errs + ['缺少题干'], []
    if q.get('type') == 'choice':
        if not q.get('choices') or q.get('answer') not in [c[0] for c in q['choices']]: errs.append('答案不在选项里')
        texts = [c[1].strip() for c in q.get('choices', [])]
        if len(set(texts)) != len(texts): errs.append('选项重复')
    elif q.get('type') == 'fill':
        if not q.get('answer') or not isinstance(q['answer'], list): errs.append('填空题答案应为可接受答案列表')
    elif q.get('type') == 'writing':
        n = len(re.findall(r"[A-Za-z]+(?:'[a-z]+)?", q.get('sample', '')))
        if n < q.get('minWords', 0): errs.append(f"范文只有 {n} 词，少于要求的 {q.get('minWords')} 词")
        B, irr = bands(); bad = out_of_band(q.get('sample', ''), q['grade'], B, irr)
        if bad and len(bad) / (n or 1) > lv['grades'][str(q['grade'])]['newWords'] + .02:
            warns.append('范文超纲词：' + ', '.join(sorted(set(bad))))
        return errs, warns
    else: errs.append('type 只能是 choice、fill 或 writing')
    if errs: return errs, warns
    right = ' '.join(c[1] for c in q.get('choices', []) if c[0] == q['answer'])
    stem = q['stem'] + ' ' + right + ' ' + q.get('passage', '')
    for quoted in re.findall(r'"([^"]+)"', q['stem']): stem = stem.replace(quoted, ' ')
    bad = [] if q['topic'].startswith('ph.') else out_of_band(stem, q['grade'], B, irr)
    words = len(re.findall('[A-Za-z]+', stem)) or 1
    if bad and len(bad) / words > lv['grades'][str(q['grade'])]['newWords']:
        warns.append('超纲词：' + ', '.join(sorted(set(bad))))
    longest = max((len(x.split()) for x in re.split(r'[.!?—]', q['stem']) if x.strip()), default=0)
    if not q.get('passage') and longest > lv['grades'][str(q['grade'])]['maxWords'] + 2:
        warns.append(f'句子 {longest} 词，超出建议长度')
    return errs, warns

# ---------- 年级匹配 ----------
def rec_difficulty(grade, topic_grade):
    gap = grade - topic_grade
    return [] if gap < 0 else [1, 2] if gap == 0 else [1, 2, 3] if gap == 1 else [2, 3]

def grade_rate(st, tid, grade):
    """该年级真卷里的考频；没有分年级数据时用总体考频。"""
    x = st.get(tid, {}); bg = (x.get('byGrade') or {}).get(str(grade))
    return bg['rate'] if bg and bg.get('papers', 0) >= 5 else x.get('paperRate', 0)

def select(grade, n=20, seed=None):
    """按年级抽题：题目年级在 [g-1, g]，难度落在推荐区间，按考频加权，尽量不重复知识点。"""
    T = {t['id']: t for t in load('topics.json')}
    st = load('exam_stats.json')['topics'] if (D / 'exam_stats.json').exists() else {}
    pool = [q for q in load('questions.json')
            if grade - 1 <= q['grade'] <= grade and q['difficulty'] in rec_difficulty(grade, T[q['topic']]['grade'])]
    rnd = random.Random(seed); used = collections.Counter(); out = []
    while pool and len(out) < n:
        w = [(1 + 2 * grade_rate(st, q['topic'], grade)) / (1 + 3 * used[q['topic']]) for q in pool]
        q = rnd.choices(pool, w)[0]; pool.remove(q); used[q['topic']] += 1; out.append(q)
    return out

# ---------- 出题提示词（实现见 scripts/gen.py：知识点 + 年级 + 语料库 + 真题母题） ----------
def build_prompt(tid, grade, diff=None, n=5, qtype=None, seed=None):
    import gen
    return gen.build_task(tid, grade, diff, n, qtype, seed)['prompt']

# ---------- 大模型接口：直接出题 + 盲解复核 ----------
def llm_config():
    """读 llm.json（项目根目录，不要分享），没有就读环境变量 LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL / LLM_API_KEY。"""
    f = ROOT / 'llm.json'
    cfg = json.loads(f.read_text()) if f.exists() else {}
    for k in ('provider', 'base_url', 'model', 'api_key'):
        cfg.setdefault(k, os.environ.get('LLM_' + k.upper(), ''))
    if cfg['provider'] == 'anthropic' and not cfg['api_key']: cfg['api_key'] = os.environ.get('ANTHROPIC_API_KEY', '')
    return cfg

def llm(prompt_text, cfg):
    """provider=openai：任何 OpenAI 兼容接口（DeepSeek、通义千问、Kimi、智谱、豆包、OpenAI…）；provider=anthropic：Claude API。"""
    if not cfg.get('api_key'): raise SystemExit('没有配置 API Key：复制 llm.example.json 为 llm.json 并填写')
    if cfg.get('provider') == 'anthropic':
        url = (cfg.get('base_url') or 'https://api.anthropic.com').rstrip('/') + '/v1/messages'
        headers = {'x-api-key': cfg['api_key'], 'anthropic-version': '2023-06-01', 'anthropic-beta': 'server-side-fallback-2026-07-01'}
        body = {'model': cfg.get('model') or 'claude-opus-5-5', 'max_tokens': 16000, 'fallbacks': 'default',
                'messages': [{'role': 'user', 'content': prompt_text}]}
    else:
        url = cfg['base_url'].rstrip('/') + '/chat/completions'
        headers = {'Authorization': 'Bearer ' + cfg['api_key']}
        body = {'model': cfg['model'], 'messages': [{'role': 'user', 'content': prompt_text}]}
    req = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', **headers})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'接口返回 {e.code}：{e.read().decode(errors="ignore")[:300]}')
    if cfg.get('provider') == 'anthropic':
        if r.get('stop_reason') == 'refusal': raise RuntimeError('模型拒绝了这次请求')
        return ''.join(b.get('text', '') for b in r['content'] if b.get('type') == 'text')
    return r['choices'][0]['message']['content']

def parse_json_array(text):
    m = re.search(r'\[.*\]', text, re.S)
    if not m: raise RuntimeError('模型没有返回 JSON 数组：' + text[:200])
    return json.loads(m.group(0))

def blind_prompt(qs, grade_name):
    lines = []
    for i, q in enumerate(qs, 1):
        lines.append(f"{i}. {q['stem']}" + (f"\n（短文）{q['passage']}" if q.get('passage') else ''))
        lines += [f"   {k}. {v}" for k, v in q.get('choices', [])]
    return (f"你是认真的英语老师。下面是给{grade_name}学生的英语题，请独立作答，每题给一个最佳答案。"
            "选择题回答选项字母；填空题回答要填的内容，多个空用逗号隔开。"
            "如果某题没有正确答案或不止一个正确答案，answer 写 \"?\"，并在 note 里说明原因。\n"
            '只输出 JSON 数组：[{"i":1,"answer":"B","note":""}]\n\n' + '\n'.join(lines))

def norm(x): return re.sub(r'\s+', ' ', re.sub(r"[.,!?;:，。！？；：]", ' ', str(x).lower().replace('’', "'"))).strip()

def blind_check(q, a):
    """盲解答案与给定答案不一致 → 返回错误说明。"""
    if not a: return '复核没有作答'
    got = str(a.get('answer', '')).strip()
    if got == '?': return '复核认为有歧义：' + str(a.get('note', ''))
    ok = got[:1].upper() == q['answer'] if q['type'] == 'choice' else any(norm(got) == norm(x) for x in q['answer'])
    return None if ok else f"复核作答为 {got}，与给定答案不一致"

def serve(port=8765):
    """本地网页 + HTTP API。浏览器不直接连大模型（避开跨域），密钥只放在 llm.json 里。
    GET  /api/llm-config                         当前出题模型
    GET  /api/topics?grade=6                     知识点（含该年级考频、常见考法）
    GET  /api/exemplars?topic=&grade=&qtype=&k=  真题母题
    GET  /api/blueprint?grade=7                  该年级真卷结构
    POST /api/task     {topic,grade,difficulty,n,qtype,material}   → 提示词 + 母题 + task_id（交给任何 AI）
    POST /api/ingest   {task_id, reply|questions, blind}           → 机检 + 真题依据检查，通过的写入 data/待审题目/
    POST /api/generate {topic,grade,difficulty,n,qtype,provider,model,verify}  → 服务端直接调模型出题
    POST /api/llm      {prompt, cfg}                               → 透传给模型（网页用）
    """
    import gen, urllib.parse
    import api
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(ROOT / 'app'), **k)
        def send_json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8'); self.send_header('Content-Length', str(len(b)))
            self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                if u.path == '/api/llm-config':
                    c = gen.llm_config(); return self.send_json(200, {'configured': bool(c.get('api_key')) or c.get('provider') in ('codex', 'claude', 'cli'),
                                                                     'provider': c.get('provider'), 'model': c.get('model')})
                if u.path.startswith('/api/') and u.path[5:] in api.GET:
                    return self.send_json(200, api.GET[u.path[5:]](**q))
            except (ValueError, KeyError, TypeError) as e: return self.send_json(400, {'error': str(e)})
            super().do_GET()
        def do_POST(self):
            if self.client_address[0] not in ('127.0.0.1', '::1'): return self.send_json(403, {'error': '只接受本机请求'})
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])) or b'{}')
            name = self.path.split('?')[0][5:]
            try:
                if name == 'llm':
                    cfg = req.get('cfg') if (req.get('cfg') or {}).get('api_key') else gen.llm_config()
                    return self.send_json(200, {'text': gen.call_model(req['prompt'], cfg)})
                if name in api.POST: return self.send_json(200, api.POST[name](**req))
                return self.send_json(404, {'error': 'not found'})
            except (ValueError, KeyError, TypeError) as e: self.send_json(400, {'error': str(e)})
            except BaseException as e: self.send_json(502, {'error': str(e)})
    print(f'打开 http://localhost:{port}  （Ctrl+C 停止）；API 说明见 docs/API.md')
    http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()

# ---------- 题库：老师可编辑的文本 → questions.json ----------
def _parse_tail_meta(s):
    m = re.fullmatch(r'\{(.+)\}', s.strip())
    if not m: return None
    out = {}
    for kv in re.split(r'[;；]', m.group(1)):
        if ':' in kv or '：' in kv:
            k, v = re.split(r'[:：]', kv, 1)
            k = {'题型': 'qtype', '仿': 'mimicSrc'}.get(k.strip(), k.strip())
            if v.strip(): out[k] = v.strip()
    return out

def build_questions():
    """data/questions/*.txt 格式：
         @ 知识点id
         [年级/难度] 题干 | A 选项 | B 选项 | C 选项 | =B | 解析 | {题型:单项选择; 仿:某真卷}  （末尾大括号可选）
         [年级/难度] 题干 | =答案1 ; 答案2 | 解析                                              （填空题）
         %% 题材=中国文化 | 来源=链接 | 标题=… | 题型=… | 仿=…   短文（到下一个 %% 为止），直到新的 %% 或 %%end
         ## [年级/难度] 作文题目     书面表达，到单独一行 ## 为止；里面写 任务：/要求：/要点：/词数：/好句：/题型：/仿：/范文：
    """
    out = []; passage = None; meta = {}; topic = None
    for f in sorted((D / 'questions').glob('*.txt')):
        lines = f.read_text().split('\n'); i = 0; n = collections.Counter()
        while i < len(lines):
            line = lines[i].strip(); i += 1
            if not line or (line.startswith('#') and not line.startswith('## ')): continue
            if line.startswith('@'): topic = line[1:].strip(); continue
            if line == '%%end': passage = None; meta = {}; continue
            if line.startswith('%%'):
                meta = dict(kv.split('=', 1) for kv in line[2:].split(' | ') if '=' in kv)
                meta = {{'题材': 'theme', '来源': 'source', '标题': 'title', '题型': 'qtype', '仿': 'mimicSrc'}.get(k.strip(), k.strip()): v.strip()
                        for k, v in meta.items() if v.strip()}
                buf = []
                while not lines[i].strip().startswith('%%'): buf.append(lines[i].rstrip()); i += 1
                i += 1; passage = '\n'.join(buf).strip(); continue
            if line.startswith('## '):
                m = re.match(r'## \[(\d)/(\d)\]\s*(.+)', line); w = {}; key = None
                while lines[i].strip() != '##':
                    k = re.match(r'(任务|要求|要点|词数|好句|题型|仿|范文)：(.*)', lines[i].strip())
                    if k and key != '范文': key = k.group(1); w[key] = k.group(2).strip()
                    elif key: w[key] += '\n' + lines[i].rstrip()
                    i += 1
                i += 1; n[topic] += 1
                item = {'id': f'{topic}-{n[topic]:02d}', 'topic': topic, 'grade': int(m.group(1)), 'difficulty': int(m.group(2)),
                        'type': 'writing', 'title': m.group(3).strip(), 'stem': w.get('任务', ''), 'require': w.get('要求', ''),
                        'points': [x.strip() for x in re.split('[；;]', w.get('要点', '')) if x.strip()],
                        'minWords': int(w.get('词数', 60)), 'phrases': w.get('好句', '').strip(), 'sample': w.get('范文', '').strip(), 'explain': ''}
                if w.get('题型'): item['qtype'] = w['题型'].strip()
                if w.get('仿'): item['mimicSrc'] = w['仿'].strip()
                out.append(item)
                continue
            m = re.match(r'\[(\d)/(\d)\]\s*(.*)', line)
            if not m: raise SystemExit(f'{f.name}: 看不懂这一行：{line}')
            parts = [p.strip() for p in m.group(3).split(' | ')]
            tail = _parse_tail_meta(parts[-1]) if len(parts) > 2 else None
            if tail is not None: parts = parts[:-1]
            opts = [p for p in parts[1:] if re.match(r'^[A-G] ', p)]
            ans = next(p[1:].strip() for p in parts if p.startswith('='))
            n[topic] += 1
            q = {'id': f'{topic}-{n[topic]:02d}', 'topic': topic, 'grade': int(m.group(1)), 'difficulty': int(m.group(2)),
                 'stem': parts[0], 'explain': parts[-1]}
            if opts:
                q.update(type='choice', choices=[[o[0], o[2:].strip()] for o in opts], answer=ans)
            else:
                q.update(type='fill', answer=[a.strip() for a in ans.split(';')])
            if passage: q['passage'] = passage; q.update(meta)
            if tail: q.update(tail)
            out.append(q)
    (D / 'questions.json').write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f'题库 {len(out)} 题')

# ---------- 打包 ----------
def _compact_exemplars():
    """给网页离线使用的精简真题母题包：每个知识点×年级保留最多 4 道单题 + 每年级各篇章/作文题型保留最多 2 篇。"""
    if not (D / 'exam_items.json').exists(): return {'items': {}, 'blocks': {}}
    import corpus as C, gen
    items_out, blocks_out = {}, {}
    for t in load('topics.json'):
        tid = t['id']
        for g in range(max(3, t['grade']), 8):
            ex = C.exemplars(tid, g, k=4)
            if ex:
                items_out[f'{tid}:{g}'] = [{'src': e.get('tag') or e['src'], 'grade': e['grade'], 'kind': e['kind'],
                                            'qtype': e['qtype'], 'text': e['text'][:240]} for e in ex]
    for q in gen.PASSAGE_Q + gen.WRITING_Q:
        for g in (3, 4, 5, 6, 7):
            bs = C.exemplar_blocks(q, g, k=2)
            if bs:
                blocks_out[f'{q}:{g}'] = [{'src': b['src'], 'grade': b['grade'], 'kind': b['kind'], 'qtype': b['qtype'],
                                           'head': b['head'][:80], 'n': b['n'], 'text': b['text'][:1200]} for b in bs]
    return {'items': items_out, 'blocks': blocks_out}

def bundle():
    data = {k: load(f'{k}.json') for k in ('topics', 'dependencies', 'levels', 'questions', 'exam_stats', 'wordlists')}
    if (D / 'exam_blueprint.json').exists(): data['exam_blueprint'] = load('exam_blueprint.json')
    data['exemplars'] = _compact_exemplars()
    (ROOT / 'app' / 'data.js').write_text('window.KB=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';')
    print('app/data.js', round((ROOT / 'app' / 'data.js').stat().st_size / 1024), 'KB')
    # 托管发布版：去掉文档骨架（发布时会自动加），把数据内联成单文件
    html = (ROOT / 'app' / 'index.html').read_text()
    html = re.sub(r'<!doctype html>\n|<html[^>]*>\n|</?head>\n|</?body>\n|</html>\n?|<meta charset[^>]*>\n|<meta name="viewport"[^>]*>\n', '', html)
    js = (ROOT / 'app' / 'data.js').read_text().replace('</', '<\\/')
    html = html.replace('<script src="data.js"></script>', '<script>window.KB_HOSTED=true;' + js + '</script>')
    (ROOT / 'app' / 'publish.html').write_text(html)
    print('app/publish.html', round(len(html.encode()) / 1024), 'KB')

def _flags(args):
    pos, kv = [], {}
    i = 0
    while i < len(args):
        x = args[i]
        if x.startswith('--'):
            k = x[2:].replace('-', '_')
            if '=' in k: k, v = k.split('=', 1); kv[k] = v
            elif i + 1 < len(args) and not args[i + 1].startswith('--'): kv[k] = args[i + 1]; i += 1
            else: kv[k] = True
        else:
            pos.append(x)
        i += 1
    return pos, kv

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help', 'help'): print(__doc__); sys.exit()
    cmd = a[0]; pos, kv = _flags(a[1:])
    if cmd == 'import':
        import corpus; corpus.import_dir(pos[0], kv.get('prefix', ''))
    elif cmd == 'items':
        import corpus; corpus.build_items()
    elif cmd == 'stats':
        stats(pos[0] if pos else None)
    elif cmd == 'topics':
        import api
        r = api.get_topics(kv.get('grade') or (pos[0] if pos else None), kv.get('domain'), kv.get('q'))
        for t in r['topics']:
            fmts = ' '.join(f'{k}({v})' for k, v in list((t.get('formats') or {}).items())[:3])
            print(f"{t['id']:22s} {t['grade']}年级 {t['paperRate']*100:4.0f}%  {t['name']}  {fmts}")
    elif cmd == 'exemplars':
        import api
        r = api.get_exemplars(pos[0], int(pos[1]), kv.get('qtype'), int(kv.get('k', 6)), int(kv['seed']) if 'seed' in kv else None)
        if 'formatProfile' in r:
            print('考法分布：', ' · '.join(f"{x['qtype']}({x['count']})" for x in r['formatProfile']))
        for i, e in enumerate(r.get('exemplars') or r.get('blocks') or [], 1):
            print(f"\n[{i}] {e.get('tag') or e['src']} ({e['grade']}年级·{e['kind']}·{e['qtype']})\n{e['text']}")
    elif cmd == 'blueprint':
        import api
        r = api.get_blueprint(pos[0] if pos else kv.get('grade'))
        gs = {str(r['grade']): r} if 'grade' in r else r['grades']
        for g, v in gs.items():
            print(f"=== {g}年级（{v['papers']} 份卷）===")
            for s in v['sections']:
                print(f"  {s['qtype']:8s}  出现率 {s['rate']*100:3.0f}%  平均 {s['items']} 小题")
    elif cmd == 'check':
        sys.exit(0 if check() else 1)
    elif cmd == 'prompt':
        import gen
        t = gen.build_task(pos[0], int(pos[1]), int(pos[2]) if len(pos) > 2 else None, int(pos[3]) if len(pos) > 3 else 5,
                           kv.get('qtype'), int(kv['seed']) if 'seed' in kv else None, kv.get('material', ''))
        print(t['prompt'])
    elif cmd == 'task':
        import gen
        t = gen.new_task(pos[0], int(pos[1]), int(pos[2]) if len(pos) > 2 else None, int(pos[3]) if len(pos) > 3 else 5,
                         kv.get('qtype'), int(kv['seed']) if 'seed' in kv else None, kv.get('material', ''))
        print(t['prompt'] + gen.agent_footer(t))
    elif cmd == 'blind':
        import api
        r = api.post_blind(pos[0])
        print(r['prompt'])
    elif cmd == 'ingest':
        import api, gen
        bf = pathlib.Path(kv['blind']).read_text() if 'blind' in kv else None
        rep = api.post_ingest(pos[0], blind=bf, model=kv.get('model', 'local-agent'), verify=bool(kv.get('verify')))
        gen.print_report(rep)
        sys.exit(0 if rep['passed'] else 1)
    elif cmd == 'generate':
        import gen
        gen.generate(pos[0], int(pos[1]), int(pos[2]) if len(pos) > 2 else None, int(pos[3]) if len(pos) > 3 else 5,
                     qtype=kv.get('qtype'), verify=not bool(kv.get('no_verify')), provider=kv.get('provider'),
                     model=kv.get('model'), seed=int(kv['seed']) if 'seed' in kv else None, material=kv.get('material', ''))
    elif cmd == 'serve':
        serve(int(pos[0]) if pos else 8765)
    elif cmd == 'mcp':
        import mcp_server; mcp_server.serve_stdio()
    elif cmd == 'select':
        for q in select(int(pos[0]), int(pos[1]) if len(pos) > 1 else 20):
            print(f"[{q['grade']}年级·难度{q['difficulty']}] {q['topic']}: {q['stem']}")
    elif cmd == 'questions':
        build_questions()
    elif cmd == 'bundle':
        bundle()
    else:
        print(f'未知命令：{cmd}\n'); print(__doc__); sys.exit(1)
