"""Compile verified public-school exercises into unit-wide CPP pools."""
import collections
import hashlib
import re

import corpus
import real_pool
from session_corpus import (STARTER_KEYS, STOP, LEADING, TAGS, FUNCTIONS, grammar_matches,
                            advanced_grammar, norm, keywords, forms, tokens)

CONFIG = {'grades': {'G0': [3,4,5], 'G1': [3,4,5], 'G2': [4,5,6], 'G3': [5,6,7]},
          'counts': {'phonics':2,'vocab':5,'grammar':10,'dialogue':2,'reading':1}, 'special':10}
# Topic anchors complement the exact four taught word lists across textbook editions.
THEMES = {
    '年龄':'birthday age', '学校':'classroom schoolbag pencil eraser classmate teacher playground',
    '玩具':'toy doll robot kite ball game', '居住空间':'bedroom kitchen bathroom livingroom apartment',
    '动物':'animal rabbit zoo panda giraffe elephant', '颜色':'colour color red yellow brown purple',
    '食物':'food rice egg bread soup fruit chicken milk noodles lunch dinner breakfast',
    '家务':'chores sweep laundry clean cook wash', '作息':'routine bedtime breakfast wake',
    '衣物':'clothing clothes shirt coat scarf sweater dress socks jacket shoes trousers', '季节':'season spring summer autumn winter',
    '家庭':'family father mother aunt brother sister cousin grandpa', '朋友':'friend friendship classmate',
    '身体':'body arm leg eye nose ear', '绘画':'paint drawing crayon sketch', '社区':'community library museum neighbourhood hospital',
    '庆祝':'festival party celebrate invitation birthday gift', '健康':'healthy health diet exercise',
    '地貌':'mountain valley river landscape', '音乐':'music guitar drum piano concert song', '恐龙':'dinosaur fossil extinct',
    '空闲':'hobby leisure pastime', '英雄':'hero brave rescue', '发明':'invent invention inventor machine',
    '栖息地':'habitat forest jungle desert ocean', '艺术':'artist painting sculpture artwork',
    '旅行':'travel trip holiday ticket train airport journey', '交通':'bus subway bicycle railway',
    '运动':'sports basketball football volleyball match race team', '历史':'history ancient historical',
    '电器':'electricity electrical battery power energy', '演出':'concert performance stage musician',
}


PUBLIC = {'河南小升初分班真卷', '2027小升初-分类卷', '2027郑州小升初名校AK真题卷',
          *[f'A+全程练考卷-{n}年级' for n in range(3,7)], *[n+'年级上' for n in '三四五六']}
SCORE = re.compile(r'[（(][^()（）\n]{0,18}\d+(?:\.\d+)?\s*分[^()（）\n]{0,12}[)）]|(?:每(?:小)?题|共)\s*\d+\s*分')
DEPEND = re.compile(r'\[图\]|看图|如图|下图|图片|图中|示意图|录音|请听|听音|图示|听力|根据图|插图')
OPT = re.compile(r'(?:^|\s+)([A-G])[.．]\s*')
SECTION = re.compile(r'^(?:#+\s*)?([一二三四五六七八九十]+)[、.．]')
ANS_NUM = re.compile(r'(?<!\S)(\d{1,2})\s*[.．、]\s*')
KEY_HEADER = re.compile(r'^(?:Unit\s*[A-Za-z0-9一二三四五六]+|第\s*\d+\s*周|期中|期末|月考|普通学校卷|重点学校卷|阶段检测|高频|易错|专项)',re.I)


def title_key(s):
    s=re.sub(r'^\d+_', '',s).lower()
    for word,n in zip('one two three four five six'.split(),'123456'):
        s=s.replace('unit'+word,'unit'+n).replace('unit '+word,'unit'+n)
    s=re.sub(r'[\s_（）()·~～—-]','',s)
    school=re.search(r'(普通学校卷|重点学校卷)[一二三123]$',s)
    if school:return school[0]
    if s in ('期中考试卷','期中全真模拟训练密卷'):return '期中考试卷'
    week=re.match(r'第(\d+)周',s)
    return '第'+week[1]+'周' if week else s.replace('文字版','')


def answer_books(papers):
    """Join on printed paper title, written section and original number; never on a partial title."""
    result={}
    for coll in sorted(PUBLIC):
        collpapers=[p for p in papers if p['collection']==coll]
        ref=next((p for p in collpapers if p['kind']=='答案'),None)
        if not ref:continue
        titles={title_key(p['title']):p['file'] for p in collpapers if p['kind']!='答案'}
        file=section=None
        for line in (corpus.CORPUS/ref['file']).read_text().splitlines():
            line=line.strip().lstrip('#').strip()
            if (title_key(line) in titles or KEY_HEADER.match(line) or line.endswith('密卷')) and not SECTION.match(line):
                file=titles.get(title_key(line));section=None
                continue
            if not file:continue
            if '听力部分' in line or '笔试部分' in line:
                section=None
                if '笔试部分' in line:
                    result[file]={}
                continue
            m=SECTION.match(line)
            if m:section=m[1];line=line[m.end():].strip()
            if not section:continue
            if re.match(r'^[（(][一二三四五]',line):
                section=None
                continue
            nums=list(ANS_NUM.finditer(line))
            for i,mark in enumerate(nums):
                answer=line[mark.end():nums[i+1].start() if i+1<len(nums) else None].strip()
                if not answer or len(answer)>120:continue
                slot=(section,int(mark[1]))
                keys=result.setdefault(file,{})
                if slot in keys and keys[slot]!=answer:keys[slot]=''
                else:keys[slot]=answer
    return result


def clean(s):
    return SCORE.sub('',corpus.norm_item(s)).strip()


def key_for(keys,file,head,no):
    sec=SECTION.match(head)
    return keys.get(file,{}).get((sec[1],int(no)),'') if sec else ''


def split_item(raw):
    raw=clean(corpus.TAG.sub('',raw))
    m=LEADING.match(raw)
    if not m:return None
    body=re.sub(r'^[(（]\s*[）)]\s*','',raw[m.end():]).strip()
    parts=OPT.split(body)
    labels=parts[1::2]
    if labels and (labels!=list('ABCDEFG'[:len(labels)]) or len(labels)<2):return None
    opts=[s.strip() for s in parts[2::2]]
    if len(set(map(norm,opts)))!=len(opts) or any(not v for v in opts):return None
    return int(m[1]),parts[0].strip(),opts


def with_key(stem,opts,key,head):
    if not key:return None
    if opts:
        if key in opts:return key
        return opts[ord(key)-65] if re.fullmatch('[A-G]',key) and ord(key)-65<len(opts) else None
    if re.fullmatch(r'[A-G]',key) and not re.search(r'字母|拼写',head):return None
    if re.fullmatch(r'[TF√×]',key) and not re.search('判断|正误|相同',head):return None
    if re.search(r'略|示例|提示|得分|评分|听力|笔试|解析[:：]|[一二三四五六七八九十]、',key):return None
    return key


def source_allowed(p):
    return p['collection'] in PUBLIC and p['kind']!='答案' and not p.get('ocr') and not re.search(
        r'机构内部|内部单元测|(?:CPP|KP)[ _-]*(?:G\d[ _-]*)?(?:Unit|单元)|Unit Test',p['file'],re.I)


def original_sections(papers):
    for paper in papers.values():
        if paper['grade']==7:continue
        text=(corpus.CORPUS/paper['file']).read_text()
        segments=re.split(r'(?m)^\s*(?:#+\s*)?([一二三四五六七八九十]+[、.．][^\n]+)\s*$',text)
        for head,body in zip(segments[1::2],segments[2::2]):
            if DEPEND.search(head) or '听' in head:continue
            if re.search('答语|选择.*答句|情景|交际|补全.*对话|对话.*补充|完成对话',head):typ='情景交际'
            elif re.search('阅读|读短文|读.{0,4}文章',head):typ='阅读理解'
            else:continue
            body=clean(body)
            if re.search(r'任务[一二]|[（(][一二][）)]|写一篇|写一段|^#(?!#*\s*第)',body,re.M):continue
            count=len(re.findall(r'(?m)^\s*(?:[（(]\s*[）)]\s*)?\d{1,2}[.．、]\s*',body))
            yield dict(id='unit-'+hashlib.sha256((paper['file']+head).encode()).hexdigest()[:16],
                       file=paper['file'],grade=paper['grade'],head=head,text=body,n=count,qtype=typ,topics=corpus.tag_item(body,typ,head))


def build_bank(exams,papers,units,review,lessons):
    allowed={p['file']:p for p in papers if source_allowed(p)}
    paired=answer_books(papers)
    rows={}
    for row in exams['items']:
        file=row['file']
        if file not in allowed or row['pic'] or row['ocr']:continue
        head=clean(row['head']);qtype=row['qtype'];raw=row['text']
        if qtype not in ('语音辨音','字母','不同类','单项选择','情景交际','适当形式','翻译','连词成句','句型转换','首字母填空','汉语提示填词'):continue
        if DEPEND.search(head+raw) or re.search(r'根据.{0,8}(?:短文|表格|信息|文章)|连线|左右栏|阅读|读短文|方框|匹配|\[表\]|#{2}|见上|下列材料',head+raw):continue
        pieces=split_item(raw)
        if not pieces:continue
        no,stem,opts=pieces
        if re.search(r'画线|划线',head+stem) and '<u>' not in raw:continue
        if re.search(r'答语|答句|问句|选出.{0,6}(?:选项|句子)',head) and not opts:continue
        if not stem and not opts:continue
        if qtype=='单项选择' and not stem:continue
        if qtype in ('单项选择','情景交际') and not opts:continue
        if re.search(r'\n\s*[(（]\s*[）)]\s*\d+[.．]|\n\s*(?:#{1,3}|[一二三四五六七八九十]+[、])',raw):continue
        official=key_for(paired,file,head,no)
        key=with_key(stem,opts,official,head)
        if not key:
            key=with_key(stem,opts,review.get(row['id']) or STARTER_KEYS.get(row['id']),head)
        if not key:continue
        if '不同类' in head or '同类' in head:qtype='不同类'
        if qtype=='字母' and not re.search('大小写|顺序|字母表|相邻',head):continue
        rows[row['id']]=dict(id=row['id'],source=real_pool.format_src(allowed[file],row.get('tag','')),file=file,grade=row['grade'],
            head=SECTION.sub('',head).strip(),stem=stem,options=opts,key=key,qtype=qtype,no=no,topics=row['topics'])
        if row.get('explain'):rows[row['id']]['explain']=row['explain']
    # Keep self-contained passages and dialogue banks together with ALL their numbered subquestions.
    for b in [*exams['blocks'],*original_sections(allowed)]:
        typ=b['qtype'];file=b['file']
        if file not in allowed or typ not in ('阅读理解','补全对话','情景交际'):continue
        dialogue=typ!='阅读理解'; body=clean(b['text'])
        if DEPEND.search(body+b['head']) or '|' in body or len(body)>6000 or len(body)<45:continue
        markers=list(re.finditer(r'(?m)^\s*(?:[（(]\s*[）)]\s*)?(\d{1,2})[.．、]\s*',body))
        if not markers or len(markers)!=b['n'] or (dialogue and len(markers)!=5):continue
        if len(set(m[1] for m in markers))!=len(markers):continue
        context=body[:markers[0].start()].strip()
        if not dialogue and not context:continue
        shared=dialogue and all(re.search(r'(?:^|\s)'+k+r'[.．]',context) for k in 'ABCDE')
        columns=[]
        if dialogue and not shared and not context:
            for i,m in enumerate(markers):
                raw=body[m.end():markers[i+1].start() if i+1<len(markers) else None].strip()
                col=re.split(r'\s+'+chr(65+i)+r'[.．]\s*',raw,maxsplit=1)
                if len(col)!=2 or OPT.search(col[1]):break
                columns.append(col)
            if len(columns)==5:
                shared=True
                context='　'.join(chr(65+i)+'. '+c[1] for i,c in enumerate(columns))
            else:columns=[]
        subs=[]
        for i,m in enumerate(markers):
            sub=(int(m[1]),columns[i][0],[]) if columns else split_item(body[m.start():markers[i+1].start() if i+1<len(markers) else None])
            if not sub:break
            n,stem,opts=sub
            val=key_for(paired,file,b['head'],n)
            checked=review.get(b['id'])
            if not val and isinstance(checked,list) and len(checked)==len(markers):val=checked[i]
            if shared:
                if not re.fullmatch('[A-E]',val):break
            elif dialogue and not opts:break
            elif opts:
                val=with_key(stem,opts,val,b['head'])
            elif val not in ('T','F','√','×'):break
            if not val or not stem:break
            subs.append(dict(stem=stem,options=opts,key=val))
        if len(subs)!=len(markers):continue
        rows[b['id']]=dict(id=b['id'],file=file,source=real_pool.format_src(allowed[file]),grade=b['grade'],qtype=typ,
            head=SECTION.sub('',clean(b['head'])).strip(),stem=context,options=[],parts=subs,topics=b['topics'])
    # Letter-writing sections often have no topic tags and are absent from exam_items.
    for file,paper in allowed.items():
        if paper['grade']>5:continue
        for sec in corpus.parse_paper((corpus.CORPUS/file).read_text()):
            head=clean(sec['head'])
            if not re.search('字母.*(?:大写|小写)|(?:大小写|相邻).*字母',head) or DEPEND.search(head):continue
            for raw in sec['items']:
                item=split_item(raw)
                if not item:continue
                n,stem,opts=item;key=key_for(paired,file,head,n)
                if not re.fullmatch('[a-zA-Z]',key) or not re.fullmatch(r'[A-Za-z]\s*_+|_+\s*[A-Za-z]',stem):continue
                id='letter-'+hashlib.sha256((file+head+str(n)).encode()).hexdigest()[:16]
                rows[id]=dict(id=id,file=file,grade=paper['grade'],source=real_pool.format_src(paper),qtype='字母',
                    head=SECTION.sub('',head),stem=stem,options=[],key=key,topics=['ph.letters'],no=n)
    rows.update((q['id'],q) for q in reviewed_groups(allowed))
    return index_units(rows,units,lessons)


def index_units(rows,units,lessons):
    routes={}; used=set()
    for card in units['units']:
        if card['level'] not in CONFIG['grades']:continue
        scopes=lessons['levels'][card['level']][card['unit']]['sessions']
        core=(w for s in scopes if s['id'] in ('S1','S2','S3','S7') for w in s['words'])
        wordset={form for w in core for form in forms(norm(w))}-STOP
        theme={v for zh,english in THEMES.items() if zh in card['theme'] for w in english.split() for v in forms(w)}
        ph=card['phonics']; phwords=set(map(norm,ph['words']))
        grammar={t for g in card['grammar'] for t in g['topics']}
        fn=set(card['pragmatics']['topics'])
        goals=card['pragmatics']['zh']+' '+card['pragmatics']['en']
        unit={b:{} for b in CONFIG['counts'] if b!='phonics' or card['level'] in ('G0','G1')}
        for id,q in rows.items():
            if q['grade'] not in CONFIG['grades'][card['level']]:continue
            qt=q['qtype'];topics=set(q['topics'])
            text=q['stem']+' '+' '.join(q['options'])+' '+' '.join(p['stem'] for p in q.get('parts',[]))
            words=tokens(text); hits=wordset & (words | tokens(q.get('key','')))
            hits.update(w for w in wordset if ' ' in w and re.search(r'\b'+re.escape(w)+r'\b',norm(text)))
            theme_hits=theme & words
            matches={}
            if 'parts' in q:
                block='reading' if qt=='阅读理解' else 'dialogue'
                cnt=len(re.findall(r"[a-z]+(?:'[a-z]+)?",q['stem'],re.I))
                if block=='reading' and card['level'] in ('G0','G1') and not 15<=cnt<=65:continue
                if block=='dialogue' and (topics & ((grammar|fn)-{'fn.dialogue','sy.yes_no','sy.basic_patterns'}) or any(re.search(a,goals,re.I) and re.search(b,text,re.I) for a,b in FUNCTIONS)):
                    matches[block]=2
                elif len(theme_hits)>=2 or hits-keywords('good new school have happy great nice'):matches[block]=1
            elif qt in ('语音辨音','字母'):
                marked=set(map(norm,re.findall(r'<u>(.*?)</u>',text,re.I)))
                patterns=tokens(ph['rule'])-set('initial ending sounds long short sound vowels consonants blends and the alphabet hard soft controlled diphthongs'.split())
                if 'phonics' in unit and (words & phwords or marked & patterns or qt=='字母' and 'alphabet' in ph['rule'].lower()):
                    matches['phonics']=2
            else:
                if any(grammar_matches(g['name'],g['zh'],q) or advanced_grammar(g['name'],q) for g in card['grammar']):
                    matches['grammar']=2
                elif topics & grammar and qt in ('适当形式','句型转换','连词成句') and any(g['name'].lower() in ('present simple','tense review') for g in card['grammar']):
                    matches['grammar']=1
                lexical_hits=hits | theme_hits
                if lexical_hits and (qt in ('不同类','翻译','连词成句','汉语提示填词','首字母填空') or
                             qt=='单项选择' and lexical_hits & tokens(q.get('key',''))):
                    matches['vocab']=1
            for block,priority in matches.items():
                unit[block][id]=priority;used.add(id)
        routes[card['id']]=unit
    return {'config':CONFIG,'routes':routes,'items':{k:{a:b for a,b in q.items() if a!='topics'} for k,q in rows.items() if k in used}}


def reviewed_groups(allowed):
    """Self-contained original subsections missed by the general exam parser."""
    for file,start,end,keys in [
        ('四年级上/01_Unit1_过关测试密卷.txt','I’m Xu Nana.','（一）根据文中','TTFT'),
        ('六年级上/01_Unit1_过关测试密卷.txt','1. I’m Binbin.','（一）给 1，2','TFTT')]:
        if file not in allowed:continue
        raw=(corpus.CORPUS/file).read_text()
        begin=raw.index(start);stop=raw.index(end,begin)
        passage=raw[begin:stop].replace('[图]','').strip()
        head='（二）判断句子正（T）误（F）。'
        section=raw[raw.index(head,stop):].split('###',1)[0]
        statements=re.findall(r'(?m)^（\s*）\d+\.\s*(.+)',section)
        if len(statements)!=len(keys):raise ValueError(file+' 阅读题号变动')
        yield dict(file=file,grade=allowed[file]['grade'],id='reading-'+str(allowed[file]['grade'])+'-u1',
                   source=real_pool.format_src(allowed[file]),qtype='阅读理解',head='判断句子正（T）误（F）。',
                   stem=passage,options=[],topics=[],parts=[dict(stem=s,options=[],key=k) for s,k in zip(statements,keys)])
    file='2027小升初-分类卷/14_第六部分 题型三 补全对话.txt'
    if file not in allowed:return
    raw=(corpus.CORPUS/file).read_text()
    for n,keys in [(1,'EADCB'),(2,'EBCDA'),(4,'EFABD'),(6,'CEABD'),(7,'ADCBE')]:
        source,text=re.search(r'^Dialogue '+str(n)+r' (.+)\n([\s\S]*?)(?=^Dialogue \d+ |\Z)',raw,re.M).groups()
        passage=text.replace('[图]','').strip()
        if re.findall(r'(\d+)\.\s*_+',passage)!=list('12345'):raise ValueError(file+' 对话题号变动')
        yield dict(id='dialogue-entrance-'+str(n),file=file,grade=7,source=source.split('★')[0].strip()+' · 小升初分类卷',
                   qtype='情景交际',head='选择恰当的选项，补全对话。',stem=passage,options=[],topics=['fn.dialogue'],
                   parts=[dict(stem='第 '+str(i)+' 空 ______',options=[],key=k) for i,k in enumerate(keys,1)])
