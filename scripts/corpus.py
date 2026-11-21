#!/usr/bin/env python3
"""语料库与真题题目库（仅标准库）。

  导入：把试卷的文字版（.md / .txt / .docx / 有文字层的 .pdf）清洗后放进 corpus/<套卷名>/，
        每份卷子登记年级、卷子类型，写 data/corpus_index.json。
  拆题：把语料库里每份卷子拆成「大题（题型）→ 小题」，给每道小题标知识点，写 data/exam_items.json。
  蓝图：统计每个年级真卷的大题结构，写 data/exam_blueprint.json。
  检索：exemplars(知识点, 年级, 题型) 返回最该模仿的真题原题——AI 出题、组卷、题库锚定都从这里取。
"""
import json, re, collections, pathlib, subprocess, hashlib, statistics, random, difflib
from kb import ROOT, D, load, bands, option_topic

CORPUS = ROOT / 'corpus'

# ---------- 卷子元数据 ----------
GRADE_WORDS = [(7, r'小升初|分班|入学|新初一|AK|暗考|名校真'), (3, r'三年级|3年级|三上|三下'), (4, r'四年级|4年级|四上|四下'),
               (5, r'五年级|5年级|五上|五下'), (6, r'六年级|6年级|六上|六下')]
SKIP_WORDS = r'高一|高二|高三|高中|中考|七上|七下|八上|八下|九上|九下|初二|初三|雅思|IELTS|FCE|托福'
KINDS = [  # 卷子类型 → 出题时的权重：真题优先
    ('答案', r'答案|解析版?$'),
    ('真题', r'真题|真卷|名校|学校卷|期末测试|期末试卷|学情调研|AK|分类卷'),
    ('模拟', r'期中|期末|月考|阶段检测|综合测试|全真模拟|检测卷|Revision'),
    ('专项', r'专项|专题|过关检测|高频|易错|提优|分类|考点'),
    ('同步', r'Unit|第\d+周|单元|过关测试'),
]
KIND_WEIGHT = {'真题': 1.0, '模拟': .75, '专项': .65, '同步': .55}

def paper_meta(rel):
    s = str(rel)
    if re.search(SKIP_WORDS, s): return None
    grade = next((g for g, r in GRADE_WORDS if re.search(r, s)), None)
    kind = next((k for k, r in KINDS if re.search(r, s)), '模拟')
    return {'grade': grade, 'kind': kind}

def clean_md(text):
    text = text.replace('\r', '')
    out = []
    for line in text.split('\n'):
        if line.startswith('>') and ('阅读说明' in line or re.match(r'>\s*\d+\.\s', line) or 'AI' in line): continue
        if re.match(r'^\|?\s*(题号|项目|得分|\|)', line) or re.match(r'^\|[-| ]+\|$', line): continue
        if re.match(r'^<!--.*-->$', line.strip()) or line.strip() in ('---', '视频讲解'): continue
        line = re.sub(r'!\[[^\]]*\]\([^)]*\)', '[图]', line)
        line = re.sub(r'^>\s?', '', line)
        line = line.replace('**', '')
        out.append(line.rstrip())
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip() + '\n'

def read_any(f):
    suf = f.suffix.lower()
    if suf in ('.md', '.txt'): return f.read_text(errors='ignore')
    if suf in ('.docx', '.doc'):
        r = subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(f)], capture_output=True, text=True)
        return r.stdout
    if suf == '.pdf':
        r = subprocess.run(['pdftotext', '-layout', str(f), '-'], capture_output=True, text=True)
        return r.stdout if len(re.findall('[A-Za-z]{3,}', r.stdout)) > 200 else ''   # 扫描件没有文字层
    return ''

def import_dir(src, collection_prefix=''):
    """把 src 下的试卷文字版导入 corpus/。同一试卷的 .md 优先，跳过图片版、听力音频、中学材料。"""
    src = pathlib.Path(src); added = skipped = 0; report = collections.Counter()
    files = [f for f in src.rglob('*') if f.is_file() and not f.name.startswith('._') and f.name != '目录.md'
             and f.suffix.lower() in ('.md', '.txt', '.docx', '.doc', '.pdf')]
    for f in sorted(files):
        rel = f.relative_to(src)
        meta = paper_meta(rel)
        if not meta: report['中学/国际材料，跳过'] += 1; continue
        if f.suffix.lower() == '.pdf' and any(f.with_suffix(x).exists() for x in ('.md', '.txt')): continue
        text = read_any(f)
        if len(re.findall('[A-Za-z]{3,}', text)) < 30: report['没有可用文字（扫描件或图片），跳过'] += 1; skipped += 1; continue
        if meta['grade'] is None: report['看不出年级，跳过'] += 1; skipped += 1; continue
        collection = collection_prefix + rel.parts[0] if len(rel.parts) > 1 else collection_prefix + '散卷'
        name = (rel.parts[-2] if len(rel.parts) > 2 else f.stem)
        out = CORPUS / collection / (re.sub(r'[\\/:*?"<>|]', '_', name) + '.txt')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(clean_md(text))
        added += 1; report[f'{meta["grade"]}年级·{meta["kind"]}'] += 1
    print(f'导入 {added} 份到 corpus/，跳过 {skipped} 份')
    for k, v in sorted(report.items()): print(f'  {k}: {v}')
    build_index()

def build_index():
    """登记 corpus/ 下全部卷子。根目录的旧卷是河南小升初/分班真卷（扫描件 OCR 按每 4 页一份）。"""
    idx = []
    for f in sorted(CORPUS.rglob('*.txt')):
        rel = f.relative_to(CORPUS)
        if len(rel.parts) == 1:
            meta = {'grade': 7, 'kind': '真题'}
            coll = '河南小升初分班真卷（扫描OCR）' if f.name.startswith('ocr_') else '河南小升初分班真卷'
        else:
            meta = paper_meta(rel) or {'grade': None, 'kind': '模拟'}; coll = rel.parts[0]
            if meta['grade'] is None: continue
        idx.append({'file': str(rel), 'title': f.stem.replace('ocr_', '扫描:'), 'collection': coll,
                    'grade': meta['grade'], 'kind': meta['kind'], 'ocr': f.name.startswith('ocr_'), 'chars': f.stat().st_size})
    (D / 'corpus_index.json').write_text(json.dumps(idx, ensure_ascii=False, indent=0))
    c = collections.Counter((x['grade'], x['kind']) for x in idx)
    print(f'语料库共 {len(idx)} 份：' + '，'.join(f'{g}年级{k} {n}' for (g, k), n in sorted(c.items())))
    return idx

# ---------- 拆题：大题（题型）→ 小题 ----------
# (题型, 标题/说明里的关键词, 输出形式)。顺序有讲究：先判断篇章类，再判断单句类。
QTYPES = [
    ('听力', r'听|录音', None),
    ('书面表达', r'书面表达|作文|写作|习作|写一篇|写一封|写一段', 'writing'),
    ('完形填空', r'完形', 'passage'),
    ('语篇填空', r'短文填空|语篇填空|补全短文|阅读短文.{0,20}(填空|填词|填入|选择.{0,6}词)|根据短文内容.{0,10}填', 'passage'),
    ('任务型阅读', r'任务型|阅读.{0,20}(回答问题|完成表格|完成任务)', 'passage'),
    ('阅读理解', r'阅读|读短文|读对话|读故事|读一读|读材料', 'passage'),
    ('补全对话', r'补全对话|对话填空|完成对话|补全.{0,4}对话|对话匹配|选.{0,10}(补全|完成).{0,6}对话', 'choice'),
    ('情景交际', r'情景|交际|答语|答句|问句|相应的答', 'choice'),
    ('句型转换', r'句型转换|按要求|同义句|合并|改为|改写|画线部分提问|划线部分提问|对画线|对划线', 'fill'),
    ('连词成句', r'连词成句|连词组句|组成句子|排列.{0,6}句|连词成', 'fill'),
    ('翻译', r'翻译|汉译英|英译汉|英汉互译|译成|选择.{0,4}汉语意思|汉语意思.{0,4}选', 'fill'),
    ('适当形式', r'适当形式|正确形式|所给词|括号内.{0,8}词|用.{0,6}形式', 'fill'),
    ('首字母填空', r'首字母', 'fill'),
    ('汉语提示填词', r'汉语提示|中文提示|根据.{0,6}汉语|根据.{0,6}中文', 'fill'),
    ('选词填空', r'选词填空|方框|词汇运用|词语运用|选择.{0,6}词.{0,6}填', 'fill'),
    ('语音辨音', r'发音|读音|音标|画线部分|划线部分|语音|重读|音节', 'choice'),
    ('字母', r'字母', 'fill'),
    ('不同类', r'不同类|不同的一项|不同的选项|归类|类别', 'choice'),
    ('看图', r'看图|图片|图意|图画', 'choice'),
    ('判断', r'判断|正误|对错|T\s*[)）]?\s*[或/、]|“√”|√', 'choice'),
    ('单项选择', r'单项选择|单选|选择(最佳|正确|恰当|合适)?答案|选出.{0,10}(正确|最佳|恰当|合适|不同)|选择题|选择填空|选择最佳', 'choice'),
    ('改错', r'改错|错误', 'fill'),
]
QTYPE_FORM = {q: f for q, _, f in QTYPES}
# 题型 → 这类题天然考的知识点（再加上题干/选项识别出的知识点）
QTYPE_TOPICS = {'完形填空': ['rd.cloze'], '语篇填空': ['rd.passage_fill'], '任务型阅读': ['rd.task'], '阅读理解': ['rd.detail'],
                '补全对话': ['fn.dialogue'], '情景交际': ['fn.dialogue'], '连词成句': ['sy.word_order'], '首字母填空': ['vo.spelling'],
                '汉语提示填词': ['vo.spelling'], '语音辨音': ['ph.same_sound'], '不同类': ['vo.categories'], '字母': ['ph.letters'],
                '句型转换': ['sy.paraphrase'], '书面表达': ['wr.paragraph'], '翻译': ['sy.basic_patterns'], '适当形式': ['vb.verb_forms']}
READING_SKILLS = [('rd.main_idea', r'best title|main idea|mainly (about|tell)|标题|主旨|主要讲'),
                  ('rd.inference', r'we can (know|learn|infer)|infer|probably|may be|推断|可能'),
                  ('rd.word_guess', r'underlined word|划线|画线.{0,4}词|mean[s]?\b.{0,10}\?|词义'),
                  ('rd.true_false', r'\bTRUE\b|\bFALSE\b|\bNOT true\b|which is true|which of the following is (not )?(true|right)|正误|[(（]\s*[TF]\s*[)）]'),
                  ('rd.purpose', r'writer wants|author|purpose|feel[s]? |feeling|作者|目的|感受'),
                  ('rd.structure', r'paragraph|para\.|结构|段落'),
                  ('rd.practical', r'ticket|poster|notice|timetable|menu|price|how much|海报|通知|车票')]
WRITING_TOPICS = [('wr.letter', r'信|email|邮件|dear'), ('wr.experience', r'经历|难忘|last|周末|假期|一次'),
                  ('wr.plan_wish', r'梦想|计划|将来|未来|打算|愿望|dream|plan'), ('wr.self_others', r'介绍|自我|朋友|家人|老师|my (friend|family|mother|father)'),
                  ('wr.advice', r'建议|健康|习惯|advice|should'), ('wr.culture', r'节日|传统|文化|家乡|中国|festival'), ('wr.daily', r'日常|一天|生活|周末活动|daily')]

HEAD_NUM = re.compile(r'^(?:#{1,4}\s*)?(?:[一二三四五六七八九十]{1,3}\s*[、.．]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]{1,3}\s*[、.．]?|(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\s*[、.．]|第[一二三四五六七八九十]+部分)\s*')
SCORE = re.compile(r'[(（][^()（）]*(\d+\s*分|小题|每[空题])[^()（）]*[)）]\s*[。.]?\s*$')
ITEM = re.compile(r'^\s*(?:[(（][\s　]*[)）]\s*)?(\d{1,2})\s*[.．、](?!\d)\s*(.*)$')
OPT_LINE = re.compile(r'^\s*[(（]?[A-G][)）.．]')
TAG = re.compile(r'【([^】]{2,40})】')

def is_heading(line):
    s = line.strip()
    if not s or len(s) > 120: return False
    if re.match(r'^#{1,4}\s*(第\s*\d+\s*页|成绩表|注意|参考答案)', s): return False
    if re.match(r'^#{2,4}\s', s) and re.search(r'[\u4e00-\u9fff]', s): return True
    if HEAD_NUM.match(s) and re.search(r'[\u4e00-\u9fff]{2}', s) and not ITEM.match(s): return True
    if SCORE.search(s) and re.search(r'[\u4e00-\u9fff]{3}', s) and not ITEM.match(s) and not re.search(r'[A-Za-z]{4}', s): return True
    return False

def classify(head):
    for q, r, _ in QTYPES:
        if re.search(r, head): return q
    return '其他'

def split_options(line):
    """选项粘连（A. looks; onB. watches）→ 用全角空格隔开；选项行统一成 A. x　B. y。"""
    if not OPT_LINE.match(line): return line
    return re.sub(r'(?<=[^\s　])(?=[B-G][.．]\s?\S)', '　', line)

def norm_item(text):
    text = '\n'.join(l for l in text.split('\n') if not re.match(r'^\s*(#+\s*第\s*\d+\s*页|[·—\-]\s*\d+\s*[·—\-]|第\s*\d+\s*页)\s*$', l))
    text = re.sub(r'[ \t]+', ' ', text).strip()
    text = re.sub(r'_{3,}', '______', text)
    return text

def parse_paper(text):
    """→ [(大题标题, 题型, 引导文字/短文, [小题文本...])]。听力部分整体跳过。"""
    sections = []; cur = None; listening = False
    lines = [split_options(l) for l in text.split('\n')]
    for line in lines:
        s = line.strip()
        if not s: continue
        if re.match(r'^#*\s*听力部分', s): listening = True; continue
        if re.match(r'^#*\s*(笔试部分|笔试|读写部分)', s): listening = False; continue
        if is_heading(s):
            head = re.sub(r'^#+\s*', '', s)
            q = classify(HEAD_NUM.sub('', head))
            cur = {'head': head, 'qtype': '听力' if listening and q != '书面表达' else q, 'intro': [], 'items': []}
            sections.append(cur); continue
        if cur is None: continue
        m = ITEM.match(s)
        if m and not re.match(r'^\d{1,2}\s*[.．、]\s*_{2,}\s*\d', s):   # “21. ____ 22. ____” 是答题格，不是题
            cur['items'].append(s)
        elif OPT_LINE.match(s) and cur['items']:
            cur['items'][-1] += '\n' + s
        elif cur['items'] and cur['qtype'] in ('句型转换', '补全对话', '情景交际', '单项选择', '适当形式') and len(cur['items'][-1]) < 200 and not cur['intro'][-1:] == [s]:
            cur['items'][-1] += '\n' + s      # 题干换行、对话第二行、句型转换的答题行
        else:
            cur['intro'].append(s)
    if len(sections) <= 1 and not any(sec['items'] for sec in sections):   # 没有大题标题的老卷（OCR）：整卷当一个“其他”大题
        items = [l.strip() for l in lines if ITEM.match(l.strip())]
        sections = [{'head': '', 'qtype': '其他', 'intro': [], 'items': items}]
    return sections


# ---------- 给小题标知识点 ----------
_SIG = None
def signals():
    global _SIG
    if _SIG is None:
        topics = load('topics.json')
        _SIG = [(t['id'], re.compile(s, re.I | re.M), bool(re.search(r'[\u4e00-\u9fff]', s))) for t in topics for s in t['signals']]
    return _SIG

def tag_item(text, qtype, head=''):
    _, irr = bands(); got = []
    for line in text.split('\n'):
        ot = option_topic(line, irr)
        if ot and ot not in got: got.append(ot)
    for tid, r, zh in signals():
        if tid in got: continue
        if (not zh and r.search(text)) or (zh and qtype in ('其他', '书面表达', '句型转换') and r.search(head)): got.append(tid)
    if qtype in ('阅读理解', '任务型阅读'):
        got += [tid for tid, r in READING_SKILLS if re.search(r, text, re.I) and tid not in got]
    if qtype == '书面表达':
        got += [tid for tid, r in WRITING_TOPICS if re.search(r, head + text, re.I) and tid not in got][:2]
    if qtype == '句型转换':
        for tid, r in (('sy.ask_underlined', r'画线|划线|提问'), ('sy.negative', r'否定'), ('sy.yes_no', r'一般疑问'), ('sy.paraphrase', r'同义|合并|改为')):
            if re.search(r, text + head) and tid not in got: got.append(tid)
    if qtype == '语音辨音':   # 从选项单词判断考的是短元音、magic e 还是字母组合
        ws = [w.lower() for w in re.findall(r'[A-G][.．]\s*([A-Za-z]+)', text)]
        if ws:
            if sum(bool(re.search(r'[aeiou][^aeiouwy]e$', w)) for w in ws) >= 2: got.append('ph.magic_e')
            elif sum(bool(re.search(r'ee|ea|oo|ai|ay|ow|ou|ar|er|ir|ur|or|ch|sh|th|wh|ph|ck|ng|oa|oi|oy|igh', w)) for w in ws) >= 2: got.append('ph.letter_teams')
            else: got.append('ph.short_vowels')
        if re.search(r'重读|重音|升调|降调|语调', head + text): got.append('ph.stress_intonation')
    for tid in QTYPE_TOPICS.get(qtype, []):
        if tid not in got: got.append(tid)
    if qtype in ('阅读理解', '任务型阅读'):   # 阅读题只算阅读技能；短文里碰巧出现的词汇/语法不算考点
        got = [t for t in got if t.startswith('rd.')]
    elif qtype in ('完形填空', '语篇填空'):   # 完形/语篇填空：主知识点放前面，空格考的语法点保留在后面
        main = [t for t in got if t.startswith('rd.')]; got = main + [t for t in got if t not in main]
    return got[:6]

def has_blank_or_opts(text):
    return bool(re.search(r'_{2,}|[(（][\s　]*[)）]|\bA[.．]', text))

# ---------- 拆全部语料 → data/exam_items.json ----------
def build_items():
    idx = load('corpus_index.json') if (D / 'corpus_index.json').exists() else build_index()
    items, blocks = [], []; per = collections.Counter(); blueprint_raw = collections.defaultdict(list)
    for p in idx:
        if p['kind'] == '答案': continue
        text = (CORPUS / p['file']).read_text(errors='ignore')
        secs = parse_paper(text); order = []
        for si, sec in enumerate(secs):
            q = sec['qtype']
            if q == '听力': continue
            if q == '其他':   # 分类卷等：大题标题看不出题型时，用卷名判断（如“题型一 完形填空”）
                q = sec['qtype'] = classify(p['title']) if classify(p['title']) not in ('听力',) else '其他'
            order.append((q, len(sec['items'])))
            head_text = HEAD_NUM.sub('', sec['head'])
            intro = '\n'.join(sec['intro'])
            if QTYPE_FORM.get(q) in ('passage', 'writing') or (q in ('补全对话', '选词填空') and len(intro) > 80):
                body = (intro + '\n' + '\n'.join(sec['items'])).strip()
                if len(re.findall('[A-Za-z]{3,}', body)) >= 15 and '[图]' not in body[:200]:
                    bid = 'B' + hashlib.md5((p['file'] + str(si)).encode()).hexdigest()[:8]
                    blocks.append({'id': bid, 'src': p['title'], 'file': p['file'], 'grade': p['grade'], 'kind': p['kind'], 'qtype': q,
                                   'head': sec['head'], 'text': body[:2400], 'n': len(sec['items']),
                                   'topics': tag_item(body, q, head_text)})
            for it in sec['items']:
                t = norm_item(it)
                tag = TAG.search(t); src_tag = tag.group(1).strip() if tag else ''
                t = TAG.sub('', t).strip()
                words = len(re.findall('[A-Za-z]{2,}', t))
                if words < 3 or len(t) > 500: continue
                ctx = head_text + ('\n' + intro[:300] if QTYPE_FORM.get(q) == 'passage' else '')
                iid = 'R' + hashlib.md5((p['file'] + t).encode()).hexdigest()[:8]
                items.append({'id': iid, 'src': p['title'], 'file': p['file'], 'tag': src_tag, 'grade': p['grade'], 'kind': '真题' if src_tag else p['kind'],
                              'qtype': q, 'head': sec['head'][:80], 'text': t, 'pic': '[图]' in t, 'ocr': p.get('ocr', False),
                              'topics': tag_item(t, q, ctx)})
                per[p['grade']] += 1
        if order and p['kind'] in ('真题', '模拟') and not p.get('ocr'):
            blueprint_raw[p['grade']].append(order)
    seen = set(); uniq = []
    for it in items:   # 同一道题在不同汇编里重复出现，只留一份
        k = re.sub(r'\W+', '', it['text'].lower())[:120]
        if k in seen: continue
        seen.add(k); uniq.append(it)
    (D / 'exam_items.json').write_text(json.dumps({'items': uniq, 'blocks': blocks}, ensure_ascii=False, indent=0))
    bp = build_blueprint(blueprint_raw)
    tc = collections.Counter(t for it in uniq for t in it['topics'][:2])
    print(f'真题题目库：{len(uniq)} 道小题（去重前 {len(items)}），{len(blocks)} 个篇章/作文大题；按年级：' +
          '，'.join(f'{g}年级 {n}' for g, n in sorted(collections.Counter(i["grade"] for i in uniq).items())))
    none = [t['id'] for t in load('topics.json') if not tc[t['id']]]
    if none: print('  真题中没识别到的知识点：' + ', '.join(none))
    return uniq, blocks, bp

def build_blueprint(raw):
    """每个年级真卷的大题结构：出现比例、平均小题数、平均位置。组卷和出题提示词都参照它。"""
    out = {}
    for g, papers in sorted(raw.items()):
        stat = collections.defaultdict(lambda: {'papers': 0, 'counts': [], 'pos': []})
        for order in papers:
            seen = set(); n = len(order)
            for i, (q, c) in enumerate(order):
                if q == '其他': continue
                s = stat[q]
                if q not in seen: s['papers'] += 1; seen.add(q)
                s['counts'].append(c); s['pos'].append(i / max(n - 1, 1))
        rows = [{'qtype': q, 'form': QTYPE_FORM.get(q), 'rate': round(s['papers'] / len(papers), 2),
                 'items': round(statistics.median(s['counts'])) if s['counts'] else 0, 'pos': round(statistics.mean(s['pos']), 2)}
                for q, s in stat.items() if s['papers'] / len(papers) >= .08]
        out[str(g)] = {'papers': len(papers), 'sections': sorted(rows, key=lambda r: r['pos'])}
    (D / 'exam_blueprint.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out

# ---------- 检索：最该模仿的真题 ----------
_BANK = None
def bank():
    global _BANK
    if _BANK is None:
        _BANK = load('exam_items.json') if (D / 'exam_items.json').exists() else {'items': [], 'blocks': []}
        _BANK['byId'] = {x['id']: x for x in _BANK['items'] + _BANK['blocks']}
    return _BANK

def grade_weight(item_grade, grade):
    if item_grade == grade: return 1.0
    if item_grade == grade - 1: return .6
    if item_grade == grade + 1 and grade >= 5: return .35
    if grade == 7 and item_grade == 5: return .3
    return 0

def score_item(it, tid, grade, qtype=None):
    if tid not in it['topics']: return 0
    gw = grade_weight(it['grade'], grade)
    if not gw or it['pic'] or (it.get('ocr') and it['kind'] != '真题'): return 0
    s = gw * KIND_WEIGHT.get(it['kind'], .5) * (1.5, 1.0, .7, .5, .4, .3)[min(it['topics'].index(tid), 5)]
    if qtype: s *= 1.6 if it['qtype'] == qtype else .35
    if not has_blank_or_opts(it['text']) and QTYPE_FORM.get(it['qtype']) != 'fill': s *= .4
    if it.get('ocr'): s *= .6    # 扫描件 OCR 文字有错，排后面
    n = len(it['text'])
    if n < 20 or n > 320: s *= .5
    return s

def exemplars(tid, grade, qtype=None, k=6, seed=None):
    """返回最该模仿的 k 道真题（同年级、同知识点、真题优先、尽量来自不同试卷）。seed 不同时在高分候选里轮换，避免每次都抄同几道。"""
    cands = [(score_item(it, tid, grade, qtype), it) for it in bank()['items']]
    cands = sorted([c for c in cands if c[0] > 0], key=lambda c: -c[0])
    if seed is not None and len(cands) > k:
        top = cands[:max(k * 4, 20)]; rnd = random.Random(seed)
        cands = sorted(top, key=lambda c: -c[0] * (0.6 + 0.8 * rnd.random()))
    out, per_src = [], collections.Counter()
    for s, it in cands:
        if per_src[it['src']] >= 2: continue
        out.append(it); per_src[it['src']] += 1
        if len(out) >= k: break
    return out

def exemplar_blocks(qtype, grade, tid=None, k=1, seed=None):
    cands = [b for b in bank()['blocks'] if b['qtype'] == qtype and grade_weight(b['grade'], grade) and '[图]' not in b['text']]
    cands.sort(key=lambda b: -(grade_weight(b['grade'], grade) * KIND_WEIGHT.get(b['kind'], .5) * (1.3 if tid and tid in b['topics'] else 1)
                                * (1 if 300 < len(b['text']) < 2000 else .5)))
    if seed is not None: cands = cands[:8]; random.Random(seed).shuffle(cands)
    return cands[:k]

def format_profile(tid, grade):
    """该知识点在该年级（含相邻年级）真题里的考法分布：[(题型, 题数)]。"""
    c = collections.Counter()
    for it in bank()['items']:
        if tid in it['topics'] and grade_weight(it['grade'], grade) >= .6 and it['qtype'] not in ('其他', '听力'):
            c[it['qtype']] += 1
    return c.most_common()

def option_count(items):
    ns = [len(re.findall(r'(?:^|[\s　])[A-G][.．]', it['text'])) for it in items]
    ns = [n for n in ns if n >= 2]
    return collections.Counter(ns).most_common(1)[0][0] if ns else None

def similarity(a, b):
    a = re.sub(r'[^a-z ]', '', a.lower()); b = re.sub(r'[^a-z ]', '', b.lower())
    return difflib.SequenceMatcher(None, a.split(), b.split()).ratio() if a and b else 0

if __name__ == '__main__':
    import sys
    a = sys.argv[1:]
    if a and a[0] == 'import': import_dir(a[1])
    elif a and a[0] == 'index': build_index()
    elif a and a[0] == 'items': build_items()
    else: print(__doc__)
