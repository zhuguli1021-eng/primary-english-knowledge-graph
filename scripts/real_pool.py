#!/usr/bin/env python3
"""从语料库构建可直接抽题组卷的结构化真题池（data/real_pool.json）。

特点：
1. 每道真题保留精确来源（如「2026 郑州 FYWGY 学校 · 2027小升初-分类卷」或「六年级上 · 普通学校卷（一）」）。
2. 自动与语料库中的配套答案卷（三~六年级上/21_参考答案、A+全程练考卷/29_答案详解）按卷名+大题号+小题号配对标准答案；
   原卷未附答案的名校真卷保留题面与选项，标记 answerVerified=False，供第四步人工校验确认或一键 AI 拟答。
3. 同时拆出四类可直接进入双向细目表的题：
   - choice（单选 / 语音辨音 / 不同类 / 情景交际）
   - fill（适当形式 / 汉语提示 / 首字母 / 句型转换 / 连词成句 / 翻译）
   - reading（阅读理解篇章组题 / 完形填空篇章组题 / 语篇填空组题）
   - writing（真卷书面表达题面）
"""
import json, re, collections, hashlib, pathlib
from kb import ROOT, D, load
import corpus as C

CN_SEC = '一二三四五六七八九十'
OPT_SPLIT = re.compile(r'(?:^|[\s　]+)[(（]?([A-D])[)）.．]\s*')

def norm_title_key(s):
    s = re.sub(r'^\d+[_.]\s*', '', s)
    s = re.sub(r'(第\d+周[_\s]*|_文字版|英语|真卷|试卷|测试卷|检测卷|密卷|闯关自测卷|综合|过关测试|过关检测|全真模拟训练|阶段检测|[（()）\s_·—-])', '', s)
    s = s.replace('UnitOne', 'Unit1').replace('UnitTwo', 'Unit2').replace('UnitThree', 'Unit3')
    s = s.replace('UnitFour', 'Unit4').replace('UnitFive', 'Unit5').replace('UnitSix', 'Unit6')
    s = s.replace('普通学校卷一', '普通学校卷1').replace('普通学校卷二', '普通学校卷2').replace('普通学校卷三', '普通学校卷3')
    s = s.replace('重点学校卷一', '重点学校卷1').replace('重点学校卷二', '重点学校卷2').replace('重点学校卷三', '重点学校卷3')
    s = re.sub(r'（一）|\(一\)', '1', s)
    s = re.sub(r'（二）|\(二\)', '2', s)
    s = re.sub(r'（三）|\(三\)', '3', s)
    return s.lower()

def parse_ans_book_pep(f):
    """解析 三~六年级上/21_参考答案.txt → {norm_paper_key: {(sec_cn, item_no): ans}}"""
    if not f.exists(): return {}
    out = collections.defaultdict(dict)
    cur_paper = None; in_written = False; cur_sec = None
    for raw in f.read_text(errors='ignore').split('\n'):
        s = raw.strip()
        if not s or s in ('左栏：', '右栏：') or re.match(r'^##\s*第\s*\d+\s*页', s): continue
        if '听力部分' in s: in_written = False; cur_sec = None; continue
        if '笔试部分' in s: in_written = True; cur_sec = None; continue
        hm = re.match(r'^#{2,3}\s+(?!第\s*\d+\s*页)(.+)$', s)
        if hm:
            cur_paper = norm_title_key(hm.group(1)); in_written = False; cur_sec = None; continue
        if not cur_paper or not in_written: continue
        m = re.match(r'^([一二三四五六七八九十])[、.．]\s*(.*)$', s)
        if m:
            cur_sec = m.group(1); s = m.group(2).strip()
        if not cur_sec or s.startswith(('（', '(')): continue
        for im in re.finditer(r'(\d{1,2})\s*[.．、]\s*([^0-9\n]+?)(?=\s+\d{1,2}\s*[.．、]|$)', s):
            ans = im.group(2).strip().rstrip('　 ;；。')
            if ans and len(ans) <= 60:
                out[cur_paper][(cur_sec, int(im.group(1)))] = ans
    return out

def parse_ans_book_aplus(f):
    """解析 A+全程练考卷/29_答案详解.txt → {index_1based: {(sec_cn, item_no): ans}}"""
    if not f.exists(): return {}
    out = collections.defaultdict(dict)
    paper_idx = 0; cur_sec = None
    for raw in f.read_text(errors='ignore').split('\n'):
        s = raw.strip()
        if not s: continue
        if s.startswith('## '):
            paper_idx += 1; cur_sec = None; continue
        if not paper_idx: continue
        m = re.match(r'^([一二三四五六七八九十])[、.．]\s*(.*)$', s)
        if m:
            cur_sec = m.group(1); s = m.group(2).strip()
        if not cur_sec or s.startswith(('(一)', '（一）', '(二)', '（二）')): continue
        for im in re.finditer(r'(\d{1,2})\s*[.．、]\s*([^0-9\n]+?)(?=\s+\d{1,2}\s*[.．、]|$)', s):
            ans = im.group(2).strip().rstrip('　 ;；。')
            if ans and len(ans) <= 60:
                out[paper_idx][(cur_sec, int(im.group(1)))] = ans
    return out

def load_answer_maps():
    pep = {}
    for coll in ('三年级上', '四年级上', '五年级上', '六年级上'):
        pep[coll] = parse_ans_book_pep(C.CORPUS / coll / '21_参考答案.txt')
    aplus = {}
    for g in (3, 4, 5, 6):
        coll = f'A+全程练考卷-{g}年级'
        aplus[coll] = parse_ans_book_aplus(C.CORPUS / coll / '29_答案详解.txt')
    return pep, aplus

def lookup_answer(p, sec_head, item_no, pep, aplus):
    m = re.match(r'^(?:#*\s*)?([一二三四五六七八九十])[、.．]', sec_head.strip())
    if not m or not item_no: return None
    sec_cn = m.group(1)
    coll = p['collection']
    if coll in pep:
        pk = norm_title_key(p['title'])
        for k, mp in pep[coll].items():
            if k and (k in pk or pk in k):
                return mp.get((sec_cn, item_no))
    if coll in aplus:
        m2 = re.match(r'^(\d{2})_', p['title'])
        if m2:
            idx = int(m2.group(1))
            if idx <= 28:
                return aplus[coll].get(idx, {}).get((sec_cn, item_no))
    return None

def format_src(p, tag=''):
    coll = p['collection']
    title = re.sub(r'^\d+[_套]\s*_?', '', p['title']).replace('_修订版', '')
    if tag:
        return f"{tag}（{coll}）"
    if coll in ('河南小升初分班真卷',):
        return title
    return f"{coll} · {title}"

def parse_choice_stem_opts(text):
    """拆出 (题干, [[A, ...], [B, ...], ...])；若不是标准 A~D 选择题则返回 None。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines: return None
    # 找第一个含 A. B. 的位置
    joined = '\n'.join(lines)
    parts = OPT_SPLIT.split(joined)
    if len(parts) < 5: return None   # 至少 A, B 两个选项
    stem = parts[0].strip()
    opts = []
    for i in range(1, len(parts) - 1, 2):
        k = parts[i]; v = parts[i + 1].strip().rstrip('　 ')
        if k and v: opts.append([k, v])
    keys = [o[0] for o in opts]
    if keys not in (['A', 'B'], ['A', 'B', 'C'], ['A', 'B', 'C', 'D']): return None
    if any(not o[1] or len(o[1]) > 80 or '[图]' in o[1] for o in opts): return None
    stem = re.sub(r'^[(（][\s　]*[)）]\s*', '', stem)
    stem = re.sub(r'^\d{1,2}\s*[.．、]\s*', '', stem)
    stem = re.sub(r'^[(（][\s　]*[)）]\s*', '', stem).strip()
    if not stem or '[图]' in stem: return None
    return stem, opts

def clean_fill_stem(text):
    s = re.sub(r'^[(（][\s　]*[)）]\s*', '', text.strip())
    s = re.sub(r'^\d{1,2}\s*[.．、]\s*', '', s).strip()
    if '[图]' in s or len(s) < 10 or len(s) > 260: return None
    if re.search(r'\bA[.．]', s): return None
    return s

def parse_passage_group(sec, p, src_label, pep, aplus):
    """将阅读理解 / 完形填空 / 阅读判断大题拆为带短文 + 小题数组的组题。"""
    qtype = sec['qtype']
    if qtype not in ('阅读理解', '完形填空', '判断'): return []
    intro_lines = [l.strip() for l in sec['intro'] if l.strip() and '[图]' not in l
                   and not re.match(r'^(阅读下面|阅读短文|请从每小题|根据材料|完形填空|[—·-]\s*\d+)', l)]
    passage = '\n'.join(intro_lines).strip()
    if len(re.findall(r'[A-Za-z]{2,}', passage)) < 30 or len(passage) > 1900: return []
    is_tf = bool(re.search(r'正.*[TF√]|误.*[TF×]|判断', sec['head'] + ' ' + '\n'.join(sec['intro'][:2])))
    qs = []
    for it in sec['items']:
        t = C.norm_item(it)
        m_no = re.match(r'^(?:[(（][\s　]*[)）]\s*)?(\d{1,2})\s*[.．、]', t)
        ino = int(m_no.group(1)) if m_no else None
        parsed = parse_choice_stem_opts(C.TAG.sub('', t))
        if parsed:
            stem, opts = parsed
        elif is_tf and qtype in ('阅读理解', '判断'):
            stem = clean_fill_stem(C.TAG.sub('', t))
            if not stem or len(re.findall(r'[A-Za-z]{2,}', stem)) < 3: continue
            opts = [['T', 'T（正确）'], ['F', 'F（错误）']]
        else:
            continue
        if qtype == '完形填空' and (not stem or re.fullmatch(r'[\d.．()（）\s]*', stem)):
            stem = f'第 {ino or len(qs) + 1} 空'
        ans_raw = lookup_answer(p, sec['head'], ino, pep, aplus)
        if ans_raw:
            ar = ans_raw.strip().replace('√', 'T').replace('×', 'F')[:1].upper()
            ans = ar if ar in [c[0] for c in opts] else ''
        else:
            ans = ''
        tids = C.tag_item(t, '阅读理解' if qtype == '判断' else qtype, sec['head'])
        top = 'rd.true_false' if opts[0][0] == 'T' else (tids[0] if tids else ('rd.cloze' if qtype == '完形填空' else 'rd.detail'))
        qs.append({
            'topic': top,
            'topics': tids[:3] or [top],
            'qtype': '阅读判断' if opts[0][0] == 'T' else qtype,
            'type': 'choice',
            'stem': stem,
            'choices': opts,
            'answer': ans,
            'answerVerified': bool(ans),
        })
    if len(qs) < 3 or len(qs) > 12: return []
    gid = 'RP' + hashlib.md5((p['file'] + passage[:120]).encode()).hexdigest()[:8]
    return [{
        'id': gid,
        'grade': p['grade'],
        'kind': p['kind'],
        'qtype': '阅读理解' if qtype == '判断' else qtype,
        'src': src_label,
        'passage': passage,
        'questions': qs,
    }]

def parse_writing_item(sec, p, src_label):
    body = '\n'.join(sec['intro'] + sec['items']).strip()
    body = re.sub(r'_{4,}', '', body).strip()
    if '[图]' in body or len(body) < 35 or len(body) > 900: return None
    if not re.search(r'写一[篇封段份]|不少于|词数|词左右|请以|假如你是|假设你是|要求[：:]', sec['head'] + '\n' + body):
        return None
    tids = C.tag_item(body, '书面表达', sec['head'])
    top = next((t for t in tids if t.startswith('wr.') and t not in ('wr.mechanics', 'wr.sentence')), 'wr.paragraph')
    tm = re.search(r'[“"]([^”"\n]{3,40})[”"]', body)
    title = tm.group(1) if tm and re.search(r'[A-Za-z]', tm.group(1)) else '书面表达'
    wm = re.search(r'(\d{2,3})\s*(?:个)?词', body)
    min_w = int(wm.group(1)) if wm else (40 if p['grade'] <= 5 else 60 if p['grade'] == 6 else 70)
    wid = 'RW' + hashlib.md5((p['file'] + body[:100]).encode()).hexdigest()[:8]
    return {
        'id': wid,
        'topic': top,
        'topics': tids[:3] or [top],
        'grade': p['grade'],
        'kind': p['kind'],
        'qtype': '书面表达',
        'type': 'writing',
        'title': title,
        'stem': body,
        'minWords': min_w,
        'src': src_label,
    }

ALLOWED_CHOICE_Q = {'单项选择', '情景交际', '语音辨音', '不同类'}
ALLOWED_FILL_Q = {'适当形式', '汉语提示填词', '首字母填空', '句型转换', '连词成句', '翻译'}

def build_pool():
    idx = load('corpus_index.json')
    pep, aplus = load_answer_maps()
    sources = []; src_idx = {}
    def sid(s):
        if s not in src_idx:
            src_idx[s] = len(sources); sources.append(s)
        return src_idx[s]

    singles, groups, writings = [], [], []
    seen_s = set()

    for p in idx:
        if p['kind'] == '答案' or p.get('ocr'): continue
        text = (C.CORPUS / p['file']).read_text(errors='ignore')
        secs = C.parse_paper(text)
        base_src = format_src(p)
        for sec in secs:
            qtype = sec['qtype']
            if qtype == '听力': continue
            if qtype == '其他' and '分类卷' in p['collection']:
                q2 = C.classify(p['title'])
                if q2 != '听力': qtype = sec['qtype'] = q2
            if qtype in ('阅读理解', '完形填空', '判断'):
                for g in parse_passage_group(sec, p, base_src, pep, aplus):
                    g['si'] = sid(g.pop('src'))
                    groups.append(g)
                continue
            if qtype == '书面表达':
                w = parse_writing_item(sec, p, base_src)
                if w:
                    w['si'] = sid(w.pop('src'))
                    writings.append(w)
                continue
            if qtype not in ALLOWED_CHOICE_Q | ALLOWED_FILL_Q:
                continue
            for it in sec['items']:
                t = C.norm_item(it)
                tag_m = C.TAG.search(t); tag = tag_m.group(1).strip() if tag_m else ''
                t_clean = C.TAG.sub('', t).strip()
                m_no = re.match(r'^(?:[(（][\s　]*[)）]\s*)?(\d{1,2})\s*[.．、]', t_clean)
                ino = int(m_no.group(1)) if m_no else None
                tids = C.tag_item(t_clean, qtype, sec['head'])
                tids = [x for x in tids if not x.startswith(('rd.', 'wr.')) or qtype in ('连词成句', '翻译')]
                if not tids: continue
                ans_raw = lookup_answer(p, sec['head'], ino, pep, aplus)
                item_src = format_src(p, tag)

                if qtype in ALLOWED_CHOICE_Q:
                    parsed = parse_choice_stem_opts(t_clean)
                    if not parsed: continue
                    stem, opts = parsed
                    if qtype == '不同类' and len(stem) <= 4:
                        stem = '选出不同类的一项：'
                    elif qtype == '语音辨音' and len(stem) <= 4:
                        stem = '选出画线部分发音不同的一项：'
                    key_dedup = re.sub(r'\W+', '', (stem + str(opts)).lower())[:100]
                    if key_dedup in seen_s: continue
                    seen_s.add(key_dedup)
                    ans = ans_raw.strip()[:1].upper() if ans_raw and ans_raw.strip()[:1].upper() in [c[0] for c in opts] else ''
                    iid = 'RS' + hashlib.md5((p['file'] + stem).encode()).hexdigest()[:8]
                    singles.append({
                        'id': iid, 'topic': tids[0], 'topics': tids[:3],
                        'grade': p['grade'], 'kind': '真题' if tag else p['kind'],
                        'qtype': qtype, 'type': 'choice',
                        'stem': stem, 'choices': opts,
                        'answer': ans, 'answerVerified': bool(ans),
                        'si': sid(item_src),
                    })
                else:
                    stem = clean_fill_stem(t_clean)
                    if not stem: continue
                    if qtype in ('适当形式', '汉语提示填词', '首字母填空') and '_' not in stem: continue
                    key_dedup = re.sub(r'\W+', '', stem.lower())[:100]
                    if key_dedup in seen_s: continue
                    seen_s.add(key_dedup)
                    ans_list = [x.strip() for x in re.split(r'[;/；]', ans_raw) if x.strip()] if ans_raw else []
                    iid = 'RF' + hashlib.md5((p['file'] + stem).encode()).hexdigest()[:8]
                    singles.append({
                        'id': iid, 'topic': tids[0], 'topics': tids[:3],
                        'grade': p['grade'], 'kind': '真题' if tag else p['kind'],
                        'qtype': qtype, 'type': 'fill',
                        'stem': stem, 'answer': ans_list, 'answerVerified': bool(ans_list),
                        'si': sid(item_src),
                    })

    out = {'sources': sources, 'singles': singles, 'groups': groups, 'writings': writings}
    raw_bytes = json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode()
    (D / 'real_pool.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    ans_cnt = sum(1 for x in singles if x['answerVerified'])
    g_ans = sum(1 for g in groups for q in g['questions'] if q['answerVerified'])
    print(f"结构化真题池 data/real_pool.json：{round(len(raw_bytes)/1024)} KB；来源 {len(sources)} 个")
    print(f"  单题 {len(singles)} 道（选择题 {sum(1 for x in singles if x['type']=='choice')} / 填空题 {sum(1 for x in singles if x['type']=='fill')}；已自动配对标准答案 {ans_cnt} 道）")
    print(f"  阅读/完形组题 {len(groups)} 篇（共 {sum(len(g['questions']) for g in groups)} 小题；已配对答案 {g_ans} 小题）")
    print(f"  真卷书面表达 {len(writings)} 道")

if __name__ == '__main__':
    build_pool()
