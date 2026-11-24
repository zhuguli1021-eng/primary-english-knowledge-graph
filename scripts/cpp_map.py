#!/usr/bin/env python3
"""将 CPP（Cambridge Primary Path V2.1）7 个级别、63 个单元的目标卡映射为知识图谱考点与双向细目表标准。

输入：/Users/ang/Documents/教学项目/CPP单元目标卡V2.1_AI资料/完整页面数据.json
输出：data/cpp_units.json
"""
import json, re, pathlib, sys
from kb import ROOT, D, load

DEFAULT_SRC = pathlib.Path('/Users/ang/Documents/教学项目/CPP单元目标卡V2.1_AI资料/完整页面数据.json')

# CPP 级别 → 建议试卷对标年级（3~7，7=小升初/衔接冲刺；老师可在组卷台自由切换）
LEVEL_GRADE = {'G0': 3, 'G1': 4, 'G2': 5, 'G3': 6, 'G4': 7, 'G5': 7, 'G6': 7}
LEVEL_STAGE = {
    'G0': '强化输出 · 口头到书面（对标三年级基础）',
    'G1': '强化输出 · 模仿句型到自己组句（对标三~四年级）',
    'G2': '强化输出 · 句子到段落（对标五年级）',
    'G3': '技能练就 · 段落到篇章+读结构（对标六年级）',
    'G4': '技能练就 · 会写到会论证（对标小升初衔接）',
    'G5': '优势学科 · 证据支持观点（对标小升初名校冲刺）',
    'G6': '优势学科 · 多源比较与学术读写（对标小升初拔高）',
}

GRAMMAR_RULES = [
    (r'present perfect|past perfect', ['te.present_perfect']),
    (r'passive', ['te.passive']),
    (r'past progressive|interrupted past', ['te.past_continuous']),
    (r'reported|embedded question', ['sy.object_clause']),
    (r'conditional|before/after/when/as|if only', ['sy.adverbial_clause']),
    (r'tense review', ['te.tense_choice']),
    (r'past simple to be', ['te.past_be']),
    (r'past simple|past tense with ago|used to', ['te.past_simple', 'vb.past_form']),
    (r'present progressive with future|present simple for future|\bwill\b|going to|future', ['te.future']),
    (r'present progressive', ['te.present_continuous', 'vb.ing_form']),
    (r'there is|there are', ['vb.there_be']),
    (r'\bhave\s*/\s*has\b|have,\s*has', ['vb.have']),
    (r'present simple|like\s*/\s*don.t like|want\s*/\s*need', ['te.present_simple']),
    (r'verb to be', ['vb.be']),
    (r'yes/no question', ['sy.yes_no']),
    (r'subject and object question', ['sy.ask_underlined']),
    (r'how much|how many|how long', ['sy.how_phrases']),
    (r'wh-\s*question', ['sy.wh_questions']),
    (r'command', ['sy.imperative']),
    (r'tag question|so,\s*such|relative', ['sy.paraphrase']),
    (r'give,\s*send,\s*take', ['sy.basic_patterns']),
    (r'\bcan\b|\bcould\b.*ability', ['vb.modal_can']),
    (r'could and would for ideas|would like', ['vb.would_like']),
    (r'should|must|have to|had to|\bmay\b|\bmight\b|modal verbs', ['vb.modal_must']),
    (r'gerund|infinitive|causative', ['vb.nonfinite']),
    (r'superlative', ['ad.superlative', 'ad.comparative_form']),
    (r'comparative', ['ad.comparative_use', 'ad.comparative_form']),
    (r'adverbs of frequency', ['ad.frequency']),
    (r'adverb', ['ad.adverb']),
    (r'prepositions of time', ['pp.time']),
    (r'prepositions of place|^prepositions$', ['pp.place']),
    (r'preposition', ['pp.common']),
    (r'possessive pronoun', ['pr.possessive_pron']),
    (r'possessive adjective', ['pr.possessive_adj']),
    (r"possessive 's|possessive noun", ['nn.possessive']),
    (r'demonstrative', ['pr.demonstrative']),
    (r'subject and object pronoun', ['pr.personal']),
    (r'reflexive', ['pr.reflexive']),
    (r'indefinite pronoun|one,\s*ones', ['pr.indefinite']),
    (r'countable', ['nn.countable']),
    (r'quantifier|too and enough', ['nn.quantity']),
    (r'\ba/an\b', ['ar.a_an']),
]

def split_words(s):
    return [w.strip() for w in re.split(r'[、，,;；\n]+', s or '') if w.strip() and w.strip() != '—']

def map_grammar(gr_list, grade):
    out = []
    for g in gr_list:
        en = g.get('语法点（教材原名）', '').strip()
        zh = g.get('中文（产品部知识地图）', '').strip()
        s = (en + ' ' + zh).lower()
        matched = []
        for pat, tids in GRAMMAR_RULES:
            if re.search(pat, s):
                for t in tids:
                    if t not in matched: matched.append(t)
        if 'te.present_simple' in matched and grade >= 5 and 'te.present_simple_3rd' not in matched:
            matched.append('te.present_simple_3rd')
        if not matched:
            matched = ['sy.basic_patterns']
        label = f"{en}" + (f"（{zh}）" if zh else '')
        out.append({
            'name': en,
            'zh': zh,
            'rule': g.get('规则说明（教材原文）', '').strip(),
            'examples': [x.strip() for x in (g.get('教材例句（原文）', '') or '').split('\n') if x.strip()][:3],
            'topics': matched,
            'label': label,
        })
    return out

def map_phonics(ph, lv_num):
    rule = (ph.get('本单元语音／拼写规则') or '').strip()
    rl = rule.lower()
    if 'alphabet' in rl: tids = ['ph.letters']
    elif 'prefix' in rl or 'suffix' in rl or '-tion' in rl or '-able' in rl or 'pre-' in rl: tids = ['vo.word_formation']
    elif 'ending -s' in rl: tids = ['nn.plural', 'vb.third_person']
    elif '-ed' in rl: tids = ['vb.past_form']
    elif 'homophone' in rl: tids = ['vo.confusables']
    elif re.search(r'short [aeiou]|initial sounds|ending sounds', rl): tids = ['ph.short_vowels']
    elif re.search(r'long [aeiou]', rl) and lv_num <= 2: tids = ['ph.magic_e']
    else: tids = ['ph.letter_teams'] + (['ph.same_sound'] if lv_num >= 2 else [])
    return {
        'rule': rule,
        'words': split_words(ph.get('练习词（录音脚本）', '')),
        'topics': tids,
    }

def map_vocab(vo, lv_num):
    kws = []
    for k in ('Key Words 1', 'Key Words 2', 'Key Words 3', 'Key Words 4', '学习指南补充词', '交际任务词'):
        kws.extend(split_words(vo.get(k, '')))
    seen = set(); uniq = [w for w in kws if not (w.lower() in seen or seen.add(w.lower()))]
    theme_tid = 'vo.basic_themes' if lv_num == 0 else 'vo.daily_themes' if lv_num == 1 else 'vo.activity_themes' if lv_num == 2 else 'vo.world_themes'
    extra = 'vo.categories' if lv_num <= 1 else 'vo.spelling'
    return {'count': len(uniq), 'words': uniq, 'topics': [theme_tid, extra]}

def map_reading(la, tx, lv_num):
    nf = la.get('阅读策略·非虚构【层级】', '')
    fi = la.get('阅读策略·虚构【层级】', '')
    s = (nf + ' ' + fi).lower()
    tids = []
    if re.search(r'main idea|summariz|theme|主旨|概括|主题', s): tids.append('rd.main_idea')
    if re.search(r'words in context|猜词义', s): tids.append('rd.word_guess')
    if re.search(r'infer|predict|conclusion|推断|预测|结论', s): tids.append('rd.inference')
    if re.search(r'author|purpose|point of view|fact|opinion|feeling|意图|视角|事实与观点|感受', s): tids.append('rd.purpose')
    if re.search(r'structure|beginning|sequenc|结构|顺序|开头', s): tids.append('rd.structure')
    if re.search(r'caption|heading|graphic|图注|标题|图表', s): tids.append('rd.practical')
    if 'rd.detail' not in tids: tids.insert(0, 'rd.detail')
    if lv_num >= 3 and 'rd.cloze' not in tids: tids.append('rd.cloze')
    texts = [{'type': t.get('文本', ''), 'title': t.get('标题／任务', ''), 'strategy': t.get('阅读策略／写作要点', '')}
             for t in tx if t.get('文本') in ('非虚构课文', '虚构课文')]
    return {'strategies': [x for x in (nf, fi) if x], 'texts': texts, 'topics': tids[:3]}

def map_writing(tx, ev, lv_num):
    wt = next((t for t in tx if '写' in t.get('文本', '') or 'Writing' in t.get('文本', '')), {})
    raw = (wt.get('标题／任务', '') + ' ' + wt.get('阅读策略／写作要点', '') + ' ' + ev.get('成果·写作成品', '')).strip()
    rl = raw.lower()
    if lv_num == 0: tids = ['wr.mechanics', 'wr.sentence']
    elif lv_num == 1: tids = ['wr.sentence', 'wr.mechanics']
    elif re.search(r'letter|email|invitation|信|邮件|邀请', rl): tids = ['wr.letter']
    elif re.search(r'narrative|diary|story|past|经历|故事|日记', rl): tids = ['wr.experience']
    elif re.search(r'future|plan|dream|wish|计划|未来|梦想', rl): tids = ['wr.plan_wish']
    elif re.search(r'persuasive|opinion|argument|advice|review|建议|观点|倡议|评论', rl): tids = ['wr.advice']
    elif re.search(r'festival|culture|region|country|brochure|节日|文化|传统|旅游', rl): tids = ['wr.culture']
    elif re.search(r'friend|family|biography|person|朋友|家人|人物', rl): tids = ['wr.self_others']
    else: tids = ['wr.daily' if lv_num <= 3 else 'wr.paragraph']
    return {'task': wt.get('标题／任务', '') or ev.get('成果·写作成品', ''), 'focus': wt.get('阅读策略／写作要点', ''), 'topics': tids}

def map_pragmatics(pr, lv_num):
    zh = pr.get('交际任务（中文）', '')
    en = pr.get('交际任务（英文）', '')
    s = (zh + ' ' + en).lower()
    if re.search(r'问路|位置|走失|lost|direction', s): tid = 'fn.ask_way'
    elif re.search(r'购买|点餐|市场|商店|菜单|礼物|buy|shop|menu|order', s): tid = 'fn.shopping'
    elif re.search(r'建议|就诊|症状|健康|情绪|应急|advice|health|doctor', s): tid = 'fn.advice_health'
    elif re.search(r'借用|求助|报修|帮助|失物|help|borrow', s): tid = 'fn.request_help'
    elif re.search(r'介绍|参观|欢迎|introduce|welcome', s): tid = 'fn.greetings'
    else: tid = 'fn.invite_suggest'
    tids = [tid] + (['fn.dialogue'] if lv_num >= 2 and tid != 'fn.dialogue' else [])
    return {'zh': zh, 'en': en, 'oracy': pr.get('口语技能（中）', ''), 'topics': tids}

def build_cpp(src_path=DEFAULT_SRC):
    raw = json.load(open(src_path))
    T = {t['id']: t for t in load('topics.json')}
    units_out = []
    for uk, u in raw['units'].items():
        lv, un = uk.split('|')
        lv_num = int(lv[1:])
        grade = LEVEL_GRADE[lv]
        pos = u['pos']
        ph = map_phonics(u.get('ph', {}), lv_num)
        vo = map_vocab(u.get('vo', {}), lv_num)
        gr = map_grammar(u.get('gr', []), grade)
        rd = map_reading(u.get('la', {}), u.get('tx', []), lv_num)
        wr = map_writing(u.get('tx', []), u.get('ev', {}), lv_num)
        pr = map_pragmatics(u.get('pr', {}), lv_num)

        # 汇总为双向细目表的纵轴知识点（保持教学主次顺序并去重）
        rows = []
        seen = set()
        def add(tids, role, basis, rec_cells):
            for tid in tids:
                if tid in T and tid not in seen:
                    seen.add(tid)
                    rows.append({'topic': tid, 'name': T[tid]['name'], 'role': role, 'basis': basis[:80], 'cells': rec_cells})

        for gi, g in enumerate(gr):
            for ti, tid in enumerate(g['topics']):
                add([tid], '语法', f"教材语法：{g['label']}",
                    {'choice': 3 if ti == 0 else 2, 'fill': 2 if ti == 0 and gi < 2 else 1, 'reading': 0, 'writing': 0})
        add([vo['topics'][0]], '词汇', f"单元核心词 {vo['count']} 个（{', '.join(vo['words'][:6])}…）", {'choice': 2, 'fill': 0, 'reading': 0, 'writing': 0})
        if len(vo['topics']) > 1:
            add([vo['topics'][1]], '词汇', f"单元核心词拼写与辨析（{', '.join(vo['words'][:6])}…）", {'choice': 0 if vo['topics'][1] == 'vo.spelling' else 2, 'fill': 3 if vo['topics'][1] == 'vo.spelling' else 0, 'reading': 0, 'writing': 0})
        add(ph['topics'][:1], '语音', f"语音：{ph['rule']}", {'choice': 2, 'fill': 0, 'reading': 0, 'writing': 0})
        add(pr['topics'][:1], '交际', f"交际任务：{pr['zh'] or pr['en']}", {'choice': 2, 'fill': 0, 'reading': 0, 'writing': 0})
        add(rd['topics'][:1], '阅读', f"阅读策略：{' / '.join(rd['strategies'])}" if rd['strategies'] else '单元课文阅读', {'choice': 0, 'fill': 0, 'reading': 4 if lv_num <= 2 else 5, 'writing': 0})
        if lv_num >= 3 and 'rd.cloze' in rd['topics']:
            add(['rd.cloze'], '阅读', '语篇综合：完形填空', {'choice': 0, 'fill': 0, 'reading': 5, 'writing': 0})
        if lv_num >= 1:
            add(wr['topics'][:1], '写作', f"写作任务：{wr['task']}", {'choice': 0, 'fill': 0 if lv_num >= 2 else 2, 'reading': 0, 'writing': 1 if lv_num >= 2 else 0})

        sg = [{'section': it.get('板块', ''), 'prompt': it.get('题目要求（原文）', ''), 'score': int(it['分值']) if str(it.get('分值', '')).isdigit() else 0}
              for it in u.get('items', []) if it.get('来源') == '学习指南（Study Guide）']

        units_out.append({
            'id': f'{lv}-{un}',
            'level': lv,
            'unit': un,
            'grade': grade,
            'theme': pos.get('单元主题', ''),
            'bigQuestionEn': pos.get('大问题（英）', ''),
            'bigQuestionZh': pos.get('大问题（中）', ''),
            'pages': pos.get('学生书页码', ''),
            'phonics': ph,
            'vocab': {'count': vo['count'], 'words': vo['words'][:45], 'topics': vo['topics']},
            'grammar': gr,
            'reading': rd,
            'writing': wr,
            'pragmatics': pr,
            'studyGuide': sg,
            'blueprintRows': rows,
        })

    levels_out = [{'id': lv['id'], 'book': lv['book'], 'grade': LEVEL_GRADE[lv['id']], 'stage': LEVEL_STAGE[lv['id']]} for lv in raw['levels']]
    out = {
        'version': 'CPP V2.1',
        'note': '依据《CPP 单元目标卡 V2.1》生成：每个单元的语音、词汇、语法、交际、阅读策略与写作任务映射到知识图谱知识点，直接驱动双向细目表（纵轴知识点 × 横轴题型）组卷。',
        'levels': levels_out,
        'units': units_out,
    }
    (D / 'cpp_units.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"已生成 data/cpp_units.json：{len(levels_out)} 个级别，{len(units_out)} 个单元；覆盖知识点 {len({r['topic'] for u in units_out for r in u['blueprintRows']})} 个")

if __name__ == '__main__':
    build_cpp(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC)
