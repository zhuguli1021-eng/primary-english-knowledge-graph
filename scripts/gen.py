#!/usr/bin/env python3
"""AI 出题核心：所有入口（命令行、本地网页、HTTP API、MCP、Codex/WorkBuddy 等智能体）共用这一份逻辑。

出题必须同时有四个依据：
  1. 知识点（data/topics.json）：说明、掌握标准、常见错误
  2. 年级（data/levels.json）：词表、句长、已学语法；知识点首学年级晚于学生年级的不出
  3. 语料库（corpus/ + data/exam_items.json）：该知识点在该年级真卷里怎么考、考多少
  4. 真题原题：每次检索 4~8 道同年级同知识点的真题作“母题”，AI 逐题仿写，并在 mimic 字段写明母题编号；
     机检会核对母题编号、和母题的相似度（防照抄）、选项个数（与真题一致）。
"""
import json, re, os, sys, datetime, subprocess, tempfile, shutil, pathlib, collections
from kb import ROOT, D, load, bands, check_one, rec_difficulty, parse_json_array
import corpus as C

WORK = ROOT / 'work'
PENDING = D / '待审题目'

# AI 能出的题型（看图、听力需要图片/音频，不让 AI 出）
CHOICE_Q = ['单项选择', '情景交际', '补全对话', '语音辨音', '不同类']
FILL_Q = ['适当形式', '首字母填空', '汉语提示填词', '选词填空', '句型转换', '连词成句', '翻译']
PASSAGE_Q = ['完形填空', '阅读理解', '语篇填空', '任务型阅读']
WRITING_Q = ['书面表达']
ALL_Q = CHOICE_Q + FILL_Q + PASSAGE_Q + WRITING_Q
DEFAULT_HEAD = {'单项选择': '单项选择。', '情景交际': '情景交际，选择恰当的答语。', '补全对话': '选择恰当选项，补全对话。',
                '语音辨音': '选出画线部分发音不同的一项。', '不同类': '选出不同类的一项。', '适当形式': '用所给单词的适当形式填空。',
                '首字母填空': '根据首字母提示填空。', '汉语提示填词': '根据汉语意思写单词，补全句子。', '选词填空': '选词填空。',
                '句型转换': '按要求完成句子。', '连词成句': '连词成句。', '翻译': '翻译句子。', '完形填空': '完形填空。',
                '阅读理解': '阅读理解。', '语篇填空': '阅读短文，填空。', '任务型阅读': '阅读短文，完成任务。', '书面表达': '书面表达。'}
FORM_RULES = {
    '单项选择': '题干用 ______ 表示空，对话用“—…  —…”；选项写在 choices 里。',
    '情景交际': '题干给出情景或问句（可以是中文情景“当你想……时，你应该说：”或英文问句），选项是答语。',
    '补全对话': '题干是一段 2~4 轮短对话，其中一句用 ______ 代替，选项是能补进去的句子。',
    '语音辨音': '题干写“选出画线部分发音不同的一项”，选项单词里用 <u></u> 标出画线字母，例如 c<u>a</u>t。',
    '不同类': '题干可写“选出不同类的一项”，选项为同一主题的词，只有一个不同类。',
    '适当形式': '句子里用 ______ 表示空，空后紧跟括号给出原词，如 ______ (go)；answer 写所有可接受的形式。',
    '首字母填空': '空格写成首字母 + ______，如 He is my b______；answer 写完整单词。',
    '汉语提示填词': '空后括号给中文提示，如 ______（赛跑）；answer 写英文单词或短语。',
    '选词填空': '题干开头列出词库（如“[ busy, quiet, kind ]”），每题一句一空；answer 写选中的词（必要时变形）。',
    '句型转换': '先写原句，括号里写要求（如“（改为一般疑问句）”“（对画线部分提问）”，画线部分用 <u></u> 标出），换行后给出带 ______ 的目标句；answer 写所有空依次用空格连起来的内容。',
    '连词成句': '题干列出打乱的单词（用逗号隔开，句末标点放括号里）；answer 写完整句子。',
    '翻译': '题干给中文句子，要求译成英文（或给英文要求译成中文），可以给出部分英文框架和 ______；answer 写参考译文。',
}

def gname(g): return load('levels.json')['grades'][str(g)]['name']

def vocab_rule(grade):
    return ('三四年级核心词（levels.json 的 grade34）' if grade <= 4 else '课标二级词表（约 500 词）及人教 PEP 三至六年级常用词'
            if grade <= 6 else '课标二级词表 + 三级词表（超出二级的词不超过 6%，生词加中文注释，如 twins(双胞胎)）')

def default_qtype(tid, grade):
    if tid == 'rd.cloze': return '完形填空'
    if tid == 'rd.passage_fill': return '语篇填空'
    if tid == 'rd.task': return '任务型阅读'
    if tid.startswith('rd.'): return '阅读理解'
    if tid.startswith('wr.') and tid not in ('wr.mechanics', 'wr.sentence'): return '书面表达'
    for q, _ in C.format_profile(tid, grade):
        if q in CHOICE_Q + FILL_Q: return q
    return '单项选择'

def ref_label(it):
    tag = f"{it['tag']}，" if it.get('tag') else ''
    return f"〔{tag}{it['src']} · {gname(it['grade'])} · {it['kind']} · {it['qtype']}〕"

# ---------- 检查参数：知识点 + 年级 ----------
def resolve(tid, grade, diff=None, qtype=None):
    T = {t['id']: t for t in load('topics.json')}
    if tid not in T: raise ValueError(f'知识点不存在：{tid}（用 kb.py topics 查看）')
    grade = int(grade)
    if grade not in (3, 4, 5, 6, 7): raise ValueError('年级只能是 3~7（7 = 小升初）')
    t = T[tid]; rec = rec_difficulty(grade, t['grade'])
    if not rec: raise ValueError(f'「{t["name"]}」首学在{gname(t["grade"])}，{gname(grade)}还没学，不能出')
    diff = int(diff) if diff else rec[len(rec) // 2]
    qtype = qtype or default_qtype(tid, grade)
    if qtype not in ALL_Q: raise ValueError(f'题型只能是：{"、".join(ALL_Q)}')
    return t, grade, diff, qtype, rec

# ---------- 提示词 ----------
def build_task(tid, grade, diff=None, n=5, qtype=None, seed=None, material=''):
    """→ {'prompt', 'refs': {R1: 真题}, 'params'}。refs 是本次出题的母题，校验时要用。"""
    t, grade, diff, qtype, rec = resolve(tid, grade, diff, qtype)
    lv = load('levels.json'); gp = lv['grades'][str(grade)]; dr = lv['difficulty'][str(diff)]
    st = load('exam_stats.json')['topics'].get(tid, {}) if (D / 'exam_stats.json').exists() else {}
    bg = (st.get('byGrade') or {}).get(str(grade), {})
    prof = C.format_profile(tid, grade)
    total = sum(c for _, c in prof)
    prof_txt = ' · '.join(f'{q} {round(c * 100 / total)}%' for q, c in prof[:6]) if total else '（语料中较少，按相邻年级和同类题型仿写）'
    rate_txt = f"{gname(grade)}真卷中 {round(bg['rate'] * 100)}% 的卷子考到（{bg['papers']} 份卷）" if bg else ''
    params = {'topic': tid, 'grade': grade, 'difficulty': diff, 'n': int(n), 'qtype': qtype, 'seed': seed}
    head = f"""你是河南小学英语命题老师。请严格模仿下面给出的【真题原题】，为【{gp['name']}】学生出题。出题必须同时围绕：知识点、年级、语料库、真题。

一、知识点：「{t['name']}」（{tid}，首学{gname(t['grade'])}）
- 说明：{t['desc']}
- 掌握标准：{'；'.join(t['evidence'])}
- 孩子常见错误（干扰项从这里来）：{'；'.join(t['errors'])}

二、年级：{gp['name']}
- 词汇只用{vocab_rule(grade)}；人名用 Tom、Amy、Mike、Chen Jie 等课本常见名。
- 单句不超过 {gp['maxWords']} 个词；本年级已学语法：{gp['grammar']}。不得用到没学过的语法点。
- 风格：{gp['style']}

三、语料库统计
- 本知识点在{gp['name']}（含相邻年级）语料中的考法：{prof_txt}。{rate_txt}
- 本次题型：「{qtype}」；难度：{diff}·{dr['name']} —— {dr['rule']}（{gp['name']}做这个点推荐难度 {'、'.join(map(str, rec))}）
"""
    if qtype in PASSAGE_Q: return _passage_task(head, t, grade, diff, int(n), qtype, seed, material, gp, params)
    if qtype in WRITING_Q: return _writing_task(head, t, grade, diff, qtype, seed, gp, params)
    ex = C.exemplars(tid, grade, qtype, k=8 if int(n) > 5 else 6, seed=seed)
    same_q = [e for e in ex if e['qtype'] == qtype]
    if len(same_q) < 2:   # 本知识点这种题型的真题少：再补同年级同题型的真题，只学版式
        extra = [it for it in C.bank()['items'] if it['qtype'] == qtype and C.grade_weight(it['grade'], grade) >= .6 and not it['pic']
                 and it not in ex and 20 < len(it['text']) < 260][:3]
        ex += extra
    refs = {f'R{i}': e for i, e in enumerate(ex, 1)}
    k = C.option_count([e for e in ex if e['qtype'] == qtype] or ex)
    real_head = next((C.HEAD_NUM.sub('', e['head']) for e in ex if e['qtype'] == qtype and e['head']), DEFAULT_HEAD[qtype])
    choice = qtype in CHOICE_Q
    ref_txt = '\n'.join(f"[{r}]{ref_label(e)}\n{e['text']}" for r, e in refs.items()) or '（语料中没有找到可用的真题，请按题型说明出题）'
    opt_rule = f'选项个数与真题一致：{k} 个（A~{"ABCDEFG"[k - 1]}）。' if choice and k else ('每题 3~4 个选项。' if choice else '')
    prompt = head + f"""- 真卷里这类大题的标题通常写作：“{real_head}”

四、真题原题（母题）—— 逐题对照仿写，不得照抄
{ref_txt}

五、仿真要求
- 每道题选一道母题，保留它的考查角度、句子结构、设空位置、选项设计和难度，只换语境、人物、词汇；同一组题尽量用不同的母题。mimic 字段写母题编号（如 "R2"）。
- 和母题的英文不能整句相同或只换一两个词（机检相似度过高会退回）。
- 版式：{FORM_RULES[qtype]}{opt_rule}
- 每题只有一个正确答案；正确答案代入后句子必须完全地道。干扰项必须是该年级孩子真会犯的错误，不出现两个都对的选项。
- 题干给足判断依据，不靠常识；每题写一句中文解析，点明判断依据。
- 只考「{t['name']}」，不要顺带考没学过的点。

六、只输出 JSON 数组（共 {n} 题），不要其他文字。每项：
{{"topic":"{tid}","grade":{grade},"difficulty":{diff},"qtype":"{qtype}","type":"{'choice' if choice else 'fill'}","stem":"...",{'"choices":[["A","..."],["B","..."],["C","..."]],"answer":"A"' if choice else '"answer":["可接受答案1","可接受答案2"]'},"explain":"中文解析","mimic":"R1"}}"""
    return {'prompt': prompt, 'refs': {r: _slim(e) for r, e in refs.items()}, 'params': params, 'optionCount': k}

def _slim(e):
    return {k: e[k] for k in ('id', 'src', 'tag', 'grade', 'kind', 'qtype', 'text') if k in e}

def _passage_task(head, t, grade, diff, n, qtype, seed, material, gp, params):
    blocks = C.exemplar_blocks(qtype, grade, t['id'], k=2, seed=seed)
    refs = {f'B{i}': b for i, b in enumerate(blocks, 1)}
    real_n = blocks[0]['n'] if blocks and blocks[0]['n'] else n
    n = n or real_n
    ref_txt = '\n\n'.join(f"[{r}]{ref_label(b)}\n{b['head']}\n{b['text'][:1500]}" for r, b in refs.items()) or '（语料中没有找到本年级的同类篇章）'
    form = {
        '完形填空': f'短文中挖 {n} 个空，写成 __1__、__2__ …；每题 stem 写“第1空”“第2空”…，选项是可填入的词或短语，主要考上下文理解，兼顾词汇和语法。',
        '语篇填空': f'短文中挖 {n} 个空，写成 __1__ (原词) 或 __1__；每题 stem 写“第1空”…，type 为 fill，answer 写可接受答案列表；如果真题是“从方框中选词”，在 passage 开头列出词库。',
        '阅读理解': f'出 {n} 道题，题型搭配参照真题：细节理解、词义猜测、推理判断、主旨/标题；每题 {4 if grade >= 6 else 3} 个选项；判断正误题用 choices [["A","T"],["B","F"]]。',
        '任务型阅读': f'出 {n} 道任务题（回答问题、补全表格或判断），type 用 choice 或 fill，与真题一致。',
    }[qtype]
    mat = ('素材如下。只取其中的事实，用自己的话改写成适合孩子读的原创短文，不要照抄原句，人名、地名、数字必须与素材一致：\n"""\n' + material[:6000] + '\n"""\n') if material else ''
    prompt = head + f"""
四、真题原题（母篇）—— 仿照它的篇幅、段落数、设空/设问方式、题目数量和选项个数
{ref_txt}

五、仿真要求
- 写一篇原创短文：约 {gp['passageWords']} 词（参照母篇长度），词汇只用{vocab_rule(grade)}，个别超纲词在词后加中文注释，如 wetland(湿地)，全文注释不超过 6 个。
- 题材贴近新课标：应用文、科普跨学科、中国文化、记叙情感 四选一，写进 theme。
- {form}
- 不得照抄母篇的句子；mimic 写母篇编号（如 "B1"）。
{mat}
- 每题标注 topic，只能从下面选：rd.detail 细节理解、rd.word_guess 词义猜测、rd.inference 推理判断、rd.main_idea 主旨标题、rd.structure 篇章结构、rd.purpose 作者意图与情感、rd.true_false 判断正误、rd.practical 应用文信息提取、rd.cloze 完形、rd.passage_fill 语篇填空、rd.task 任务型阅读；完形/语篇填空的空也可以标被考的语法点 id。

六、只输出 JSON 对象，不要其他文字：
{{"qtype":"{qtype}","title":"","theme":"记叙情感","mimic":"B1","passage":"第一段\\n第二段","questions":[{{"topic":"{t['id']}","type":"choice","stem":"...","choices":[["A","..."],["B","..."],["C","..."]],"answer":"B","explain":"中文解析，指出原文依据"}}]}}"""
    params = dict(params, n=n)
    return {'prompt': prompt, 'refs': {r: {**{k: b[k] for k in ('id', 'src', 'grade', 'kind', 'qtype', 'head', 'n')}, 'text': b['text'][:1500]} for r, b in refs.items()}, 'params': params}

def _writing_task(head, t, grade, diff, qtype, seed, gp, params):
    blocks = C.exemplar_blocks('书面表达', grade, t['id'], k=3, seed=seed)
    refs = {f'W{i}': b for i, b in enumerate(blocks, 1)}
    mn = 40 if grade <= 5 else 60 if grade == 6 else 80
    ref_txt = '\n\n'.join(f"[{r}]{ref_label(b)}\n{b['text'][:800]}" for r, b in refs.items()) or '（语料中没有本年级的书面表达真题）'
    prompt = head + f"""
四、真题原题（书面表达母题）—— 仿照它的任务写法、要点数量和词数要求
{ref_txt}

五、仿真要求
- 话题方向：「{t['name']}」（{t['desc']}）。用中文写情境任务，如“假如你是李华……请以“……”为题……”，给出 3~5 个要点，格式与母题一致。
- 词数要求 {mn} 词左右；范文只用{vocab_rule(grade)}，本年级已学语法：{gp['grammar']}；范文比要求多 10~20 词，覆盖全部要点。
- 给 3~4 个可以套用的好句型。不得照抄母题情境；mimic 写母题编号（如 "W1"）。

六、只输出 JSON 对象：{{"qtype":"书面表达","mimic":"W1","title":"英文题目","stem":"中文任务","require":"不少于{mn}词；……","points":["要点1","要点2"],"minWords":{mn},"phrases":"句型1 / 句型2","sample":"范文"}}"""
    return {'prompt': prompt, 'refs': {r: {**{k: b[k] for k in ('id', 'src', 'grade', 'kind', 'qtype')}, 'text': b['text'][:800]} for r, b in refs.items()}, 'params': params}

# ---------- 解析与校验 ----------
def parse_reply(text):
    text = str(text).strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    starts = [i for i in (text.find('['), text.find('{')) if i >= 0]
    if not starts: raise ValueError('没有找到 JSON：' + text[:200])
    if text[min(starts)] == '[': return parse_json_array(text)
    return json.loads(re.search(r'\{.*\}', text, re.S).group(0))

def normalize(v, task):
    """模型返回的题目数组 / 篇章对象 / 作文对象 → 统一的题目数组（带 qtype、mimic）。"""
    p = task['params']; tid, g, d, qtype = p['topic'], p['grade'], p['difficulty'], p['qtype']
    if isinstance(v, dict) and 'questions' in v and isinstance(v['questions'], list) and qtype not in PASSAGE_Q and not v.get('passage'):
        v = v['questions']
    if isinstance(v, list):
        out = []
        for q in v:
            if not isinstance(q, dict): continue
            q = dict(q); q.update(topic=tid, grade=g, difficulty=d, qtype=q.get('qtype') or qtype)
            q.setdefault('type', 'choice' if q.get('choices') else 'fill')
            if q['type'] == 'fill' and isinstance(q.get('answer'), str): q['answer'] = [x.strip() for x in re.split(r'\s*[;/；]\s*', q['answer']) if x.strip()]
            out.append(q)
        return out
    if v.get('passage'):
        passage = '\n'.join(x.strip() for x in str(v['passage']).split('\n') if x.strip())
        T = {t['id']: t for t in load('topics.json')}
        out = []
        for q in v.get('questions', []):
            q = dict(q); q.setdefault('type', 'choice' if q.get('choices') else 'fill')
            if q['type'] == 'fill' and isinstance(q.get('answer'), str): q['answer'] = [q['answer']]
            top = q.get('topic') if q.get('topic') in T and rec_difficulty(g, T[q['topic']]['grade']) else tid
            q.update(topic=top, grade=g, difficulty=d, qtype=qtype, passage=passage, theme=v.get('theme', ''), title=v.get('title', ''),
                     mimic=v.get('mimic', ''), source='AI 仿真题原创')
            out.append(q)
        return out
    if v.get('sample'):
        return [{'topic': tid, 'grade': g, 'difficulty': d, 'type': 'writing', 'qtype': '书面表达', 'title': v.get('title', ''),
                 'stem': v.get('stem', ''), 'require': v.get('require', ''), 'points': v.get('points', []), 'minWords': int(v.get('minWords') or 60),
                 'phrases': v.get('phrases', ''), 'sample': v['sample'], 'explain': '', 'mimic': v.get('mimic', '')}]
    raise ValueError('看不懂返回的 JSON：既不是题目数组，也不是篇章或作文')

def check_mimic(q, task, siblings=()):
    """真题依据检查：母题编号必须是本次给出的；不能照抄母题；选项个数与真题一致。→ (错误, 提醒)"""
    errs, warns = [], []
    refs = task.get('refs', {})
    m = str(q.get('mimic', '')).strip().strip('[]')
    if not refs: return errs, ['本次没有可用的真题母题']
    if not m: errs.append('缺少 mimic（仿照的真题编号），不能确认它围绕真题出题'); return errs, warns
    if m not in refs: errs.append(f'mimic={m} 不是本次给出的真题编号（可选 {"、".join(refs)}）'); return errs, warns
    ref = refs[m]
    mine = q.get('stem', '') + ' ' + ' '.join(c[1] for c in q.get('choices', []) or [])
    if q.get('passage'): mine = q['passage']
    if q.get('type') == 'writing': mine = q.get('stem', '') + q.get('sample', '')
    sim = C.similarity(mine, ref['text'])
    if sim >= (.6 if q.get('passage') else .8): errs.append(f'和母题 {m} 相似度 {sim:.0%}，像照抄真题')
    elif sim >= .6 and not q.get('passage'): warns.append(f'和母题 {m} 相似度 {sim:.0%}，请确认换了语境')
    k = task.get('optionCount')
    if k and q.get('type') == 'choice' and not q.get('passage') and len(q.get('choices') or []) != k:
        warns.append(f'选项 {len(q.get("choices") or [])} 个，真题这类题是 {k} 个')
    if q.get('qtype') and q['qtype'] != task['params']['qtype'] and q['qtype'] not in ALL_Q:
        errs.append(f'题型 {q["qtype"]} 不在可选题型里')
    return errs, warns

def validate(qs, task):
    """→ [(题, 错误, 提醒)]。题库机检（年级词表、句长、答案）+ 真题依据检查。"""
    T = {t['id']: t for t in load('topics.json')}; lv = load('levels.json'); out = []
    stems = collections.Counter(re.sub(r'\W+', '', (q.get('stem', '') + str(q.get('choices', ''))).lower()) for q in qs)
    for q in qs:
        e, w = check_one(q, T, lv)
        e2, w2 = check_mimic(q, task); e += e2; w += w2
        if q.get('type') != 'writing' and not q.get('passage') and stems[re.sub(r'\W+', '', (q.get('stem', '') + str(q.get('choices', ''))).lower())] > 1:
            e.append('本组里有重复题')
        out.append((q, e, w))
    return out

def blind_prompt(qs, grade):
    shared = qs[0].get('passage') if qs and all(q.get('passage') == qs[0].get('passage') for q in qs) else ''
    lines = ['短文：\n' + shared + '\n'] if shared else []
    for i, q in enumerate(qs, 1):
        if q.get('type') == 'writing': continue
        lines.append(f"{i}. {q['stem']}" + (f"\n（短文）{q['passage']}" if q.get('passage') and not shared else ''))
        lines += [f"   {k}. {v}" for k, v in q.get('choices', []) or []]
    return (f"你是认真的英语老师。下面是给{gname(grade)}学生的英语题，请独立作答，每题给一个最佳答案。"
            "选择题回答选项字母；填空题回答要填的内容，多个空用空格隔开。"
            "如果某题没有正确答案或不止一个正确答案，answer 写 \"?\"，并在 note 里说明原因。\n"
            '只输出 JSON 数组：[{"i":1,"answer":"B","note":""}]\n\n' + '\n'.join(lines))

def blind_errors(qs, answers):
    from kb import blind_check
    solved = {int(a.get('i', 0)): a for a in answers or []}
    return {i: blind_check(q, solved.get(i)) for i, q in enumerate(qs, 1) if q.get('type') != 'writing'}

# ---------- 保存到待审题目 ----------
def save_pending(rows, task, model='AI'):
    """通过的题写成老师可读、可直接挪进 data/questions/ 的文本格式。"""
    if not rows: return None
    p = task['params']; refs = task.get('refs', {})
    PENDING.mkdir(exist_ok=True)
    f = PENDING / f"{p['topic']}-g{p['grade']}d{p['difficulty']}-{p['qtype']}-{datetime.datetime.now():%m%d%H%M%S}.txt"
    src = lambda q: (refs.get(str(q.get('mimic', '')).strip('[]'), {}).get('tag') or refs.get(str(q.get('mimic', '')).strip('[]'), {}).get('src', '')).replace('|', '/').replace(';', '，')
    lines = [f'# {model} 仿真题出题，已过机检（年级词表、答案、仿真依据）；老师确认后把整段移到 data/questions/ 下的文件里',
             f'# 知识点 {p["topic"]} · {gname(p["grade"])} · 难度 {p["difficulty"]} · 题型 {p["qtype"]}',
             '# 母题：' + '；'.join(f'{r}={(e.get("tag") or e["src"])}' for r, e in refs.items())]
    by_topic = collections.defaultdict(list)
    for q, w in rows: by_topic[q['topic']].append((q, w))
    for tid, items in by_topic.items():
        lines.append(f'@ {tid}')
        cur_p = None
        for q, w in items:
            meta = f"{{题型:{q.get('qtype', p['qtype'])}; 仿:{src(q)}}}"
            if q.get('type') == 'writing':
                lines += [f"## [{q['grade']}/{q['difficulty']}] {q['title']}", f"任务：{q['stem']}", f"要求：{q['require']}", f"要点：{'；'.join(q['points'])}",
                          f"词数：{q['minWords']}", f"好句：{q['phrases']}", f"题型：{q.get('qtype')}", f"仿：{src(q)}", f"范文：{q['sample']}", '##']
                continue
            if q.get('passage') and q['passage'] != cur_p:
                if cur_p: lines.append('%%end')
                lines += [f"%% 题材={q.get('theme') or '记叙情感'} | 标题={q.get('title', '')} | 题型={q.get('qtype')} | 仿={src(q)}", q['passage'], '%%']
                cur_p = q['passage']
            body = ' | '.join([q['stem'].replace('\n', ' / ')] + [f'{k} {v}' for k, v in q.get('choices', []) or []])
            ans = q['answer'] if q['type'] == 'choice' else ' ; '.join(q['answer'])
            if w: lines.append('# 提醒：' + '；'.join(w))
            lines.append(f"[{q['grade']}/{q['difficulty']}] {body} | ={ans} | {q.get('explain', '').replace('|', '/')}" + ('' if q.get('passage') else f' | {meta}'))
        if cur_p: lines.append('%%end')
    f.write_text('\n'.join(lines) + '\n')
    return f

# ---------- 大模型 / 本地智能体调用 ----------
def llm_config(override=None):
    f = ROOT / 'llm.json'
    cfg = json.loads(f.read_text()) if f.exists() else {}
    for k in ('provider', 'base_url', 'model', 'api_key'):
        cfg.setdefault(k, os.environ.get('LLM_' + k.upper(), ''))
    if cfg.get('provider') == 'anthropic' and not cfg.get('api_key'): cfg['api_key'] = os.environ.get('ANTHROPIC_API_KEY', '')
    if override: cfg.update({k: v for k, v in override.items() if v})
    if not cfg.get('provider'):
        cfg['provider'] = 'openai' if cfg.get('api_key') else ('codex' if shutil.which('codex') else 'claude' if shutil.which('claude') else '')
    return cfg

def run_cli(prompt, cfg):
    """本地智能体当出题模型：codex exec / claude -p / 任意命令行（WorkBuddy、CodeBuddy、ollama 等）。提示词从 stdin 传入。"""
    prov = cfg['provider']; extra = cfg.get('args') or []
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / 'last.txt'; pf = pathlib.Path(tmp) / 'prompt.txt'; pf.write_text(prompt)
        if prov == 'codex':
            cmd = ['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only', '-o', str(out)] + (['-m', cfg['model']] if cfg.get('model') else []) + extra + ['-']
        elif prov == 'claude':
            cmd = ['claude', '-p', '--output-format', 'text'] + (['--model', cfg['model']] if cfg.get('model') else []) + extra
        else:
            c = cfg.get('command') or os.environ.get('LLM_COMMAND', '')
            if not c: raise RuntimeError('provider=cli 需要在 llm.json 里写 command，例如 ["codebuddy","-p"]')
            cmd = c if isinstance(c, list) else ['/bin/sh', '-c', c]
            cmd = [x.replace('{prompt_file}', str(pf)) for x in cmd]
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=str(ROOT), timeout=int(cfg.get('timeout') or 900))
        if r.returncode != 0: raise RuntimeError(f'{cmd[0]} 退出码 {r.returncode}：{(r.stderr or r.stdout)[-400:]}')
        return out.read_text() if out.exists() and out.stat().st_size else r.stdout

def call_model(prompt, cfg):
    if cfg.get('provider') in ('codex', 'claude', 'cli'): return run_cli(prompt, cfg)
    from kb import llm
    return llm(prompt, cfg)

# ---------- 一条龙：出题 → 校验 → 盲解复核 → 待审 ----------
def ingest(reply, task, blind_answers=None, cfg=None, verify=False, model='AI'):
    """reply：模型返回的文本或已解析的 JSON。返回报告 dict。"""
    v = parse_reply(reply) if isinstance(reply, str) else reply
    qs = normalize(v, task)
    res = validate(qs, task)
    blind = {}
    if blind_answers is None and verify and cfg and any(not e for _, e, _ in res):
        blind_answers = parse_json_array(call_model(blind_prompt(qs, task['params']['grade']), cfg))
    if blind_answers is not None: blind = blind_errors(qs, blind_answers)
    keep, report = [], []
    for i, (q, e, w) in enumerate(res, 1):
        if not e and blind.get(i): e = e + [blind[i]]
        report.append({'i': i, 'stem': (q.get('stem') or q.get('title', ''))[:80], 'mimic': q.get('mimic', ''), 'ok': not e, 'errors': e, 'warnings': w})
        if not e: keep.append((q, w))
    f = save_pending(keep, task, model)
    return {'passed': len(keep), 'total': len(qs), 'file': str(f.relative_to(ROOT)) if f else None, 'blindChecked': blind_answers is not None,
            'questions': report}

def generate(tid, grade, diff=None, n=5, qtype=None, verify=True, provider=None, model=None, seed=None, material=''):
    cfg = llm_config({'provider': provider, 'model': model})
    if not cfg.get('provider'): raise SystemExit('没有可用的出题模型：配置 llm.json（API），或安装 codex / claude 命令行，或用 --provider cli')
    task = build_task(tid, grade, diff, n, qtype, seed if seed is not None else datetime.datetime.now().microsecond, material)
    print(f"# {cfg['provider']}{('/' + cfg['model']) if cfg.get('model') else ''} 出题：{tid} · {gname(task['params']['grade'])} · {task['params']['qtype']} · 母题 {len(task['refs'])} 道", file=sys.stderr)
    rep = ingest(call_model(task['prompt'], cfg), task, cfg=cfg, verify=verify and task['params']['qtype'] not in WRITING_Q,
                 model=f"{cfg['provider']}{('/' + cfg['model']) if cfg.get('model') else ''}")
    print_report(rep)
    return rep

def print_report(rep):
    for r in rep['questions']:
        print(f"{'✓' if r['ok'] else '✗'} [{r['mimic'] or '无母题'}] {r['stem']}  {'；'.join(r['errors'] + r['warnings'])}")
    print(f"通过 {rep['passed']}/{rep['total']} 题" + (f"，写入 {rep['file']}" if rep['file'] else '') + ('' if rep['blindChecked'] else '（未做盲解复核）'))

# ---------- 智能体模式：本地 Codex / WorkBuddy / Claude Code 自己当出题模型 ----------
def new_task(tid, grade, diff=None, n=5, qtype=None, seed=None, material=''):
    task = build_task(tid, grade, diff, n, qtype, seed if seed is not None else datetime.datetime.now().microsecond, material)
    p = task['params']
    tid_ = f"{p['topic']}-g{p['grade']}d{p['difficulty']}-{p['qtype']}-{datetime.datetime.now():%m%d%H%M%S%f}"[:-3]
    task['id'] = tid_; task['out'] = f'work/out/{tid_}.json'
    (WORK / 'tasks').mkdir(parents=True, exist_ok=True); (WORK / 'out').mkdir(parents=True, exist_ok=True)
    (WORK / 'tasks' / f'{tid_}.json').write_text(json.dumps(task, ensure_ascii=False, indent=1))
    return task

def load_task(task_id):
    task_id = pathlib.Path(str(task_id)).name.replace('.blind.json', '').replace('.json', '')
    f = WORK / 'tasks' / f'{task_id}.json'
    if not f.exists(): raise ValueError(f'找不到出题任务 {task_id}（先运行 kb.py task …）')
    return json.loads(f.read_text())

def agent_footer(task):
    return f"""

────────── 给智能体（Codex / WorkBuddy / Claude Code）的操作说明 ──────────
1. 按上面的要求出题，把 JSON 原样写入文件：{task['out']}
2. （建议）运行 python3 scripts/kb.py blind {task['out']} 得到盲解提示词；不看答案独立作答，把答案 JSON 写入 {task['out'][:-5]}.blind.json
3. 运行 python3 scripts/kb.py ingest {task['out']}  —— 机检 + 真题依据检查 + 盲解比对，通过的题写入 data/待审题目/
4. 有题被退回时，按报告里的原因修改 {task['out']} 后重新 ingest。"""
