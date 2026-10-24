#!/usr/bin/env python3
"""小学英语知识库工具（仅标准库）。

  python3 scripts/kb.py stats  <语料目录>      统计真题考频、自动生成“共考”关联边 → data/exam_stats.json
  python3 scripts/kb.py questions              把 data/questions/*.txt（老师可直接编辑）编译成 data/questions.json
  python3 scripts/kb.py check                  校验知识点、先修边、题库（词汇超纲、句长、答案、重复）
  python3 scripts/kb.py prompt <知识点id> <年级3-7> <难度1-3> [题数]   生成出题提示词（给任意 AI 用）
  python3 scripts/kb.py generate <知识点id> <年级> <难度> [题数]  调大模型直接出题，质检+盲解复核后写入 data/待审题目/
  python3 scripts/kb.py serve [端口]           启动本地网页（带大模型代理），浏览器打开 http://localhost:8765
  python3 scripts/kb.py select <年级> [题数]     按年级匹配规则抽一套题（打印，便于人工看难度）
  python3 scripts/kb.py bundle                 打包成 app/data.js 供网页使用
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

def stats(corpus):
    topics = load('topics.json')
    papers = sorted(pathlib.Path(corpus).glob('*.txt'))
    sig = {t['id']: [re.compile(s, re.I | re.M) for s in t['signals']] for t in topics}
    zh = {t['id']: [bool(re.search(r'[一-鿿]', s)) for s in t['signals']] for t in topics}
    _, irr = bands()
    per_paper = collections.Counter(); hits = collections.Counter(); ex = collections.defaultdict(list)
    opt_hits = collections.Counter(); co = collections.Counter(); stem = (None, [])
    for p in papers:
        seen = set()
        src = p.stem.replace('ocr_', '扫描:')
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
        per_paper.update(seen)
    n = len(papers)
    out = {'papers': n, 'note': '按每份真卷（扫描件按每4页计一份）是否出现该知识点的信号统计；信号是关键词/正则，结果是近似值。', 'topics': {}, 'related': []}
    for t in topics:
        r = per_paper[t['id']] / n
        out['topics'][t['id']] = {'paperRate': round(r, 3), 'hits': hits[t['id']], 'optionHits': opt_hits[t['id']],
                                  'tier': 3 if r >= .5 else 2 if r >= .2 else 1, 'examples': ex[t['id']]}
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

def select(grade, n=20, seed=None):
    """按年级抽题：题目年级在 [g-1, g]，难度落在推荐区间，按考频加权，尽量不重复知识点。"""
    T = {t['id']: t for t in load('topics.json')}
    st = load('exam_stats.json')['topics'] if (D / 'exam_stats.json').exists() else {}
    pool = [q for q in load('questions.json')
            if grade - 1 <= q['grade'] <= grade and q['difficulty'] in rec_difficulty(grade, T[q['topic']]['grade'])]
    rnd = random.Random(seed); used = collections.Counter(); out = []
    while pool and len(out) < n:
        w = [(1 + 2 * st.get(q['topic'], {}).get('paperRate', 0)) / (1 + 3 * used[q['topic']]) for q in pool]
        q = rnd.choices(pool, w)[0]; pool.remove(q); used[q['topic']] += 1; out.append(q)
    return out

# ---------- 出题提示词 ----------
def build_prompt(tid, grade, diff, n=5):
    T = {t['id']: t for t in load('topics.json')}; lv = load('levels.json'); t = T[tid]
    gp = lv['grades'][str(grade)]; dr = lv['difficulty'][str(diff)]
    if diff not in rec_difficulty(grade, t['grade']):
        print(f'# 提醒：{gp["name"]}做「{t["name"]}」推荐难度 {rec_difficulty(grade, t["grade"])}，当前 {diff}。', file=sys.stderr)
    ex = load('exam_stats.json')['topics'].get(tid, {}).get('examples', []) if (D / 'exam_stats.json').exists() else []
    vocab = '三四年级核心词（levels.json 的 grade34）' if grade <= 4 else '课标二级词表（约 500 词）及人教 PEP 五六年级常用词' if grade <= 6 else '课标二级词表 + 三级词表（超出二级的词不超过 6%，生词加中文注释，如 twins(双胞胎)）'
    return f"""你是河南小学英语教研老师，为【{gp['name']}】学生出【{n}】道题，考查知识点「{t['name']}」。

知识点说明：{t['desc']}
掌握标准：{'；'.join(t['evidence'])}
孩子常见错误（干扰项从这里来）：{'；'.join(t['errors'])}

难度：{diff}·{dr['name']} —— {dr['rule']}
年级约束：
- 词汇只用{vocab}；人名用 Tom、Amy、Mike 等常见名。
- 单句不超过 {gp['maxWords']} 个词；本年级已学语法：{gp['grammar']}。不得用到没学过的语法点。
- 风格：{gp['style']}
质量要求：
- 每题只有一个正确答案；把正确答案代入后句子必须完全地道。
- 干扰项必须是该年级孩子真会犯的错误形式，不出现明显荒谬的选项，也不出现两个都对的选项。
- 题干给足判断依据，不靠常识或背景知识。
- 每题写一句中文解析，点明判断依据。
{('参考真题风格（不要照抄）：' + chr(10) + chr(10).join('- ' + e['text'] for e in ex[:4])) if ex else ''}

按 JSON 数组输出，每项：
{{"id":"{tid}-g{grade}d{diff}-01","topic":"{tid}","grade":{grade},"difficulty":{diff},"type":"choice","stem":"...","choices":[["A","..."],["B","..."],["C","..."]],"answer":"A","explain":"..."}}
填空题用 "type":"fill"，"answer" 为可接受答案列表，如 ["goes"]。只输出 JSON 数组，不要其他文字。"""


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

def generate(tid, grade, diff, n=5, verify=True):
    """调用大模型出题 → 质检 → 盲解复核 → 通过的题写进 data/待审题目/，老师审过再挪进 data/questions/。"""
    cfg = llm_config(); T = {t['id']: t for t in load('topics.json')}; lv = load('levels.json')
    qs = parse_json_array(llm(build_prompt(tid, grade, diff, n), cfg))
    for q in qs: q.update(topic=tid, grade=grade, difficulty=diff)
    solved = {}
    if verify:
        for a in parse_json_array(llm(blind_prompt(qs, lv['grades'][str(grade)]['name']), cfg)):
            solved[int(a.get('i', 0))] = a
    keep = []
    for i, q in enumerate(qs, 1):
        e, w = check_one(q, T, lv)
        if verify and not e and (b := blind_check(q, solved.get(i))): e.append(b)
        print(f"{'✗' if e else '⚠' if w else '✓'} {q.get('stem', '')[:60]}  {'；'.join(e + w)}")
        if not e: keep.append((q, w))
    if keep:
        out = D / '待审题目'; out.mkdir(exist_ok=True)
        f = out / f"{tid}-g{grade}d{diff}-{datetime.datetime.now():%m%d%H%M%S}.txt"
        rows = [f'# {cfg.get("model")} 生成，已过质检{"和盲解复核" if verify else ""}；老师确认后把整段移到 data/questions/ 下的文件里', f'@ {tid}']
        for q, w in keep:
            body = ' | '.join([q['stem']] + [f'{k} {v}' for k, v in q.get('choices', [])])
            ans = q['answer'] if q['type'] == 'choice' else ' ; '.join(q['answer'])
            rows.append((f'# 提醒：{"；".join(w)}\n' if w else '') + f"[{grade}/{diff}] {body} | ={ans} | {q.get('explain', '')}")
        f.write_text('\n'.join(rows) + '\n')
        print(f'通过 {len(keep)}/{len(qs)} 题，写入 {f.relative_to(ROOT)}')
    else:
        print(f'0/{len(qs)} 题通过')

def serve(port=8765):
    """本地网页 + /api/llm 代理：浏览器不直接连大模型（避开跨域），密钥可以只放在 llm.json 里。"""
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=str(ROOT / 'app'), **k)
        def send_json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(b)))
            self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            if self.path == '/api/llm-config':
                c = llm_config(); return self.send_json(200, {'configured': bool(c['api_key']), 'provider': c['provider'], 'model': c['model']})
            super().do_GET()
        def do_POST(self):
            if self.path != '/api/llm': return self.send_json(404, {'error': 'not found'})
            if self.client_address[0] not in ('127.0.0.1', '::1'): return self.send_json(403, {'error': '只接受本机请求'})
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            cfg = req.get('cfg') if (req.get('cfg') or {}).get('api_key') else llm_config()
            try: self.send_json(200, {'text': llm(req['prompt'], cfg)})
            except BaseException as e: self.send_json(502, {'error': str(e)})
    print(f'打开 http://localhost:{port}  （Ctrl+C 停止）')
    http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()

# ---------- 题库：老师可编辑的文本 → questions.json ----------
def build_questions():
    """data/questions/*.txt 格式：
         @ 知识点id
         [年级/难度] 题干 | A 选项 | B 选项 | C 选项 | =B | 解析        （选择题）
         [年级/难度] 题干 | =答案1 ; 答案2 | 解析                        （填空题）
         %% 题材=中国文化 | 来源=链接 | 标题=…   短文（到下一个 %% 为止），之后的题都挂在这篇短文上，直到出现新的 %% 或 %%end
         ## [年级/难度] 作文题目     书面表达，到单独一行 ## 为止；里面写 任务：/要求：/要点：/词数：/好句：/范文：（范文写在最后）
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
                meta = {{'题材': 'theme', '来源': 'source', '标题': 'title'}.get(k.strip(), k.strip()): v.strip() for k, v in meta.items()}
                buf = []
                while not lines[i].strip().startswith('%%'): buf.append(lines[i].rstrip()); i += 1
                i += 1; passage = '\n'.join(buf).strip(); continue
            if line.startswith('## '):
                m = re.match(r'## \[(\d)/(\d)\]\s*(.+)', line); w = {}; key = None
                while lines[i].strip() != '##':
                    k = re.match(r'(任务|要求|要点|词数|好句|范文)：(.*)', lines[i].strip())
                    if k and key != '范文': key = k.group(1); w[key] = k.group(2).strip()
                    elif key: w[key] += '\n' + lines[i].rstrip()
                    i += 1
                i += 1; n[topic] += 1
                out.append({'id': f'{topic}-{n[topic]:02d}', 'topic': topic, 'grade': int(m.group(1)), 'difficulty': int(m.group(2)),
                            'type': 'writing', 'title': m.group(3).strip(), 'stem': w.get('任务', ''), 'require': w.get('要求', ''),
                            'points': [x.strip() for x in re.split('[；;]', w.get('要点', '')) if x.strip()],
                            'minWords': int(w.get('词数', 60)), 'phrases': w.get('好句', '').strip(), 'sample': w.get('范文', '').strip(), 'explain': ''})
                continue
            m = re.match(r'\[(\d)/(\d)\]\s*(.*)', line)
            if not m: raise SystemExit(f'{f.name}: 看不懂这一行：{line}')
            parts = [p.strip() for p in m.group(3).split(' | ')]
            opts = [p for p in parts[1:] if re.match(r'^[A-D] ', p)]
            ans = next(p[1:].strip() for p in parts if p.startswith('='))
            n[topic] += 1
            q = {'id': f'{topic}-{n[topic]:02d}', 'topic': topic, 'grade': int(m.group(1)), 'difficulty': int(m.group(2)),
                 'stem': parts[0], 'explain': parts[-1]}
            if opts:
                q.update(type='choice', choices=[[o[0], o[2:].strip()] for o in opts], answer=ans)
            else:
                q.update(type='fill', answer=[a.strip() for a in ans.split(';')])
            if passage: q['passage'] = passage; q.update(meta)
            out.append(q)
    (D / 'questions.json').write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f'题库 {len(out)} 题')

# ---------- 打包 ----------
def bundle():
    data = {k: load(f'{k}.json') for k in ('topics', 'dependencies', 'levels', 'questions', 'exam_stats', 'wordlists')}
    (ROOT / 'app' / 'data.js').write_text('window.KB=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';')
    print('app/data.js', round((ROOT / 'app' / 'data.js').stat().st_size / 1024), 'KB')
    # 托管发布版：去掉文档骨架（发布时会自动加），把数据内联成单文件
    html = (ROOT / 'app' / 'index.html').read_text()
    html = re.sub(r'<!doctype html>\n|<html[^>]*>\n|</?head>\n|</?body>\n|</html>\n?|<meta charset[^>]*>\n|<meta name="viewport"[^>]*>\n', '', html)
    js = (ROOT / 'app' / 'data.js').read_text().replace('</', '<\\/')
    html = html.replace('<script src="data.js"></script>', '<script>window.KB_HOSTED=true;' + js + '</script>')
    (ROOT / 'app' / 'publish.html').write_text(html)
    print('app/publish.html', round(len(html.encode()) / 1024), 'KB')

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit()
    if a[0] == 'stats': stats(a[1])
    elif a[0] == 'check': sys.exit(0 if check() else 1)
    elif a[0] == 'prompt': print(build_prompt(a[1], int(a[2]), int(a[3]), int(a[4]) if len(a) > 4 else 5))
    elif a[0] == 'generate': generate(a[1], int(a[2]), int(a[3]), int(a[4]) if len(a) > 4 else 5, '--no-verify' not in a)
    elif a[0] == 'serve': serve(int(a[1]) if len(a) > 1 else 8765)
    elif a[0] == 'select':
        for q in select(int(a[1]), int(a[2]) if len(a) > 2 else 20):
            print(f"[{q['grade']}年级·难度{q['difficulty']}] {q['topic']}: {q['stem']}")
    elif a[0] == 'questions': build_questions()
    elif a[0] == 'bundle': bundle()
