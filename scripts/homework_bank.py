"""Compile verified public-school exercises into unit-wide CPP pools."""
import itertools
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
        file=section=subsection=None
        listening=False
        for line in (corpus.CORPUS/ref['file']).read_text().splitlines():
            line=line.strip().lstrip('#').strip()
            if (title_key(line) in titles or KEY_HEADER.match(line) or line.endswith('密卷')) and not SECTION.match(line):
                file=titles.get(title_key(line));section=subsection=None;listening=False
                continue
            if not file:continue
            if '听力部分' in line or '笔试部分' in line or '读写部分' in line:
                section=None
                listening='听力部分' in line
                if not listening:
                    result[file]={}
                continue
            if listening:continue
            m=SECTION.match(line)
            if m:section=m[1];subsection=None;line=line[m.end():].strip()
            if not section:continue
            # A single printed line can contain two separately numbered tasks.
            line=re.sub(r'任务([一二三四五六])\s*[:：]',r'（\1）',line)
            chunks=re.split(r'[（(]([一二三四五六])[)）]',line)
            for i in range(0,len(chunks),2):
                if i:subsection=chunks[i-1]
                part=chunks[i]
                nums=list(ANS_NUM.finditer(part))
                if '示例' in part or '答案不唯一' in part:continue
                for j,mark in enumerate(nums):
                    answer=part[mark.end():nums[j+1].start() if j+1<len(nums) else None].strip()
                    if not answer or len(answer)>120:continue
                    slot=(section,int(mark[1])) if not subsection else (section,subsection,int(mark[1]))
                    keys=result.setdefault(file,{})
                    keys[slot]=answer if keys.get(slot,answer)==answer else ''
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


ITEM_LINE = re.compile(r'(?m)^[ \t　]*(?:[（(][ \t　]*[）)][ \t　]*)?(\d{1,2})[.．、][ \t　]*')
TASK_LINE = re.compile(r'(?m)^(?:#+\s*)?[（(]([一二三四五六])[)）]([^\n]*)$')
SPEAKER = re.compile(r"(?m)^[A-Za-z][A-Za-z ’'\-]{0,24}[:：]")
METADATA = re.compile(r'^(?:\*?共\s*\d+\s*页|.*二维码|(?:\[图\]\s*)?名师解析(?:\s*\[图\])?$|[—·-]\s*\d+\s*[—·-]$|#+\s*第\s*\d+\s*页)')


def written_sections(paper):
    """Preserve printed order, without mixing listening, instructions and answerable items."""
    head=None
    lines=[]
    listening=False
    for line in (corpus.CORPUS/paper['file']).read_text().splitlines():
        s=line.strip()
        heading=s.lstrip('#').strip()
        boundary=re.match(r'^(听力部分|笔试部分|读写部分)',heading)
        if boundary or SECTION.match(heading):
            if head and not listening:yield head,clean('\n'.join(lines))
            lines=[]
            if boundary:
                listening=boundary[1]=='听力部分'
                head=None
            else:head=heading
        elif s and not METADATA.match(s):
            lines.append(s)
    if head and not listening:yield head,clean('\n'.join(lines))


def item_slices(body):
    marks=list(ITEM_LINE.finditer(body))
    return [(int(m[1]),body[m.start():marks[i+1].start() if i+1<len(marks) else None].strip()) for i,m in enumerate(marks)]


def printed_singles(sections,paper):
    """Older subject-wide index discards short questions and duplicates before grade matching."""
    for head,body in sections:
        if '听' in head or DEPEND.search(head) or TASK_LINE.search(body):continue
        body=re.sub(r'[　 \t]+(?=[（(][　 \t]*[）)]\s*\d+[.．])','\n',body)
        body=re.sub(r'　+(?=\d{1,2}[.．]\s+\S)','\n',body)
        if not ITEM_LINE.search(body):continue
        intro=body[:ITEM_LINE.search(body).start()].strip()
        wordbank=[]
        if intro:
            if not re.search('选.{0,9}(?:词|单词).{0,9}(?:句|填空)',head) or re.search('限用|一次',head):continue
            wordbank=re.split(r'[　\t]+| {2,}',intro)
            if not 2<=len(wordbank)<=7 or not all(re.fullmatch(r"[A-Za-z][A-Za-z '’\-]*",w) for w in wordbank):continue
        qt=corpus.classify(head)
        if re.search('重新排列.*单词|汉语.*字母.*补全单词|选项补全单词',head):qt='汉语提示填词'
        elif re.search('汉语意思|中文意思|汉语释义|英汉互译|给汉语选|中文.{0,4}选|译文',head):qt='翻译'
        elif re.search('汉语.{0,7}(?:写|补全)|中文.{0,5}提示',head):qt='汉语提示填词'
        elif re.search('选择.{0,4}单词补全句子',head):qt='单项选择'
        if wordbank:qt='单项选择'
        for n,raw in item_slices(body):
            if wordbank and '_' in raw and not OPT.search(raw):
                raw+='　'+'　'.join(chr(65+i)+'. '+word for i,word in enumerate(wordbank))
            if qt=='语音辨音':
                note=re.search(r'[（(]画线\s+([a-zA-Z /]+)[）)]$',raw)
                if note:
                    bits=OPT.split(raw[:note.start()])
                    sounds=[v.strip() for v in note[1].split('/')]
                    if len(sounds)==1:sounds*=len(bits[2::2])
                    if len(sounds)==len(bits[2::2]) and all(w.count(g)==1 for w,g in zip(bits[2::2],sounds)):
                        raw=bits[0]+'　'.join(l+'. '+w.replace(g,'<u>'+g+'</u>') for l,w,g in zip(bits[1::2],bits[2::2],sounds))
            if len(raw)>480 or re.search(r'[（(]\s*[)）]\s*\d+[.．]|\b\d+[.．]\s+\S',raw[raw.find('.')+1:]):continue
            # Some papers print two alternatives side-by-side without A/B labels.
            if qt=='单项选择' and not OPT.search(raw) and '_' in raw:
                fields=re.split(r'　+',raw)
                if len(fields)==3 and all(re.fullmatch(r"[A-Za-z’' -]+",v) for v in fields[1:]):
                    raw=fields[0]+'　A. '+fields[1]+'　B. '+fields[2]
            rowid='R'+hashlib.md5((paper['file']+raw).encode()).hexdigest()[:8]
            yield dict(id=rowid,file=paper['file'],grade=paper['grade'],head=head,text=raw,qtype=qt,
                       pic='[图]' in raw,ocr=False,topics=corpus.tag_item(raw,qt,head))


# These exact transcriptions were checked with the answer booklet: every blank can
# be solved from the speakers and answer bank. Other image placeholders stay blocked.
TEXT_ONLY_DIALOGUES={
    'c39923ff26037f66','a577285d306c35dc','f1067ca90f3bafcc','76d904fceea1d66c',
    '3485af618c028195','04c2e21b6ab5b4c6','6a5e0af4b0f6209a','6a93153fdf8b136a',
}


def recovered_groups(sections,paper,keys):
    file=paper['file']
    for head,body in sections:
        section=SECTION.match(head)[1]
        if DEPEND.search(head) or '听' in head or not body:continue
        if hashlib.sha256(body.encode()).hexdigest()[:16] in TEXT_ONLY_DIALOGUES:
            body=re.sub(r'(?m)^\[图\]\s*$','',body).strip()
        def group(kind,subhead,stem,parts,tag):
            return dict(id='printed-'+hashlib.sha256((file+section+tag).encode()).hexdigest()[:16],
                        file=file,grade=paper['grade'],source=real_pool.format_src(paper),qtype=kind,
                        section=section,head=clean(subhead),stem=stem,options=[],parts=parts,topics=corpus.tag_item(body,kind,head))
        # Some matching sections print the common answer bank after all five prompts.
        if re.search('答语|答句|问句|情景|交际',head) and not DEPEND.search(body) and ITEM_LINE.match(body):
            bank_start=re.search(r'(?m)^(?:- )?A[.．]\s*',body)
            if bank_start:
                prompts=body[:bank_start.start()].strip()
                bank=body[bank_start.start():].strip()
                entries=item_slices(prompts)
                answers=[keys.get((section,n),'') for n,_ in entries]
                if ([n for n,_ in entries]==list(range(1,6)) and OPT.findall(bank)==list('ABCDE')
                    and not ITEM_LINE.search(bank) and '#' not in bank and not OPT.search(prompts)
                    and sorted(answers)==list('ABCDE')):
                    parts=[dict(stem=LEADING.sub('',raw),options=[],key=answer) for (_,raw),answer in zip(entries,answers)]
                    yield group('情景交际',SECTION.sub('',head),bank,parts,'matching')
        # A five-blank dialogue with its entire bank, even when answers precede the speakers.
        if re.search('对话|聊天|交谈',head) and SPEAKER.search(body) and not DEPEND.search(body) and not TASK_LINE.search(body):
            passage=re.sub(r'(?m)^-\s+(?=[A-G][.．])','',body)
            passage=re.sub(r'(?m)^1[.．]\s*_+(?:\s+[2-5][.．]\s*_+){4}\s*$','',passage).strip()
            labels=OPT.findall(passage)
            blanks=re.findall(r'(?<!\d)(\d+)\s*[.．]?\s*_+',passage)
            answers=[keys.get((section,n),'') for n in range(1,6)]
            if (labels in [list('ABCDE'),list('ABCDEF'),list('ABCDEFG')] and blanks==list('12345')
                and all(a in labels for a in answers) and len(set(answers))==5 and '#' not in passage and '|' not in passage):
                yield group('情景交际',SECTION.sub('',head),passage,
                            [dict(stem='第 '+str(n)+' 空 ______',options=[],key=a) for n,a in enumerate(answers,1)],'dialogue')
        # Match a self-contained reading task to the exact subtask in the printed answer booklet.
        body=re.sub(r'(?m)^(#+\s*)?任务([一二三四五六])\s*[:：]',r'\1（\2）',body)
        tasks=list(TASK_LINE.finditer(body))
        if not tasks and re.search('(?:根据|阅读|读).{0,6}(?:短文|文章).{0,12}(?:判断|选择)',head) and ITEM_LINE.search(body):
            start=ITEM_LINE.search(body).start()
            body=body[:start]+'（一）'+SECTION.sub('',head)+'\n'+body[start:]
            tasks=list(TASK_LINE.finditer(body))
            standalone=True
        else:standalone=False
        if not tasks:continue
        passage=body[:tasks[0].start()].strip()
        if (len(re.findall(r'[A-Za-z]+',passage))<15 or re.search(r'\[图\]|[_|#]|[A-E][.．]\s',passage)
            or DEPEND.search(passage)):continue
        for i,m in enumerate(tasks):
            instruction=m[2]
            if DEPEND.search(instruction) or not re.search('选择|选出|判断',instruction):continue
            subtext=body[m.end():tasks[i+1].start() if i+1<len(tasks) else None].strip()
            subtext=re.sub(r'　+(?=\d{1,2}[.．]\s+\S)','\n',subtext)
            shared_options=[]
            marker=ITEM_LINE.search(subtext)
            if marker and marker.start()>0:
                bank=OPT.split(subtext[:marker.start()].strip())
                shared_options=[v.strip() for v in bank[2::2]]
                if (bank[0] or len(shared_options)<2 or bank[1::2]!=list('ABCDEFG'[:len(shared_options)])
                    or any(not v or DEPEND.search(v) for v in shared_options)):continue
                subtext=subtext[marker.start():]
            entries=item_slices(subtext)
            if (not entries or not ITEM_LINE.match(subtext) or DEPEND.search(subtext) or re.search('[|#]|画线|划线',subtext)
                or [n for n,_ in entries]!=list(range(entries[0][0],entries[0][0]+len(entries)))):continue
            parts=[]
            for n,raw in entries:
                sub=split_item(raw)
                if not sub or not sub[1]:break
                _,stem,opts=sub
                if shared_options and opts:break
                opts=opts or shared_options
                val=keys.get((section,n) if standalone else (section,m[1],n),'')
                if opts:val=with_key(stem,opts,val,instruction)
                elif val not in ('T','F','√','×'):break
                if not val:break
                parts.append(dict(stem=stem,options=opts,key=val))
            if len(parts)==len(entries):yield group('阅读理解',instruction,passage,parts,'read-'+m[1])


def build_bank(exams,papers,units,review,lessons):
    allowed={p['file']:p for p in papers if source_allowed(p)}
    paired=answer_books(papers)
    rows={}
    printed={file:list(written_sections(p)) for file,p in allowed.items() if p['grade'] in range(3,7)}
    extra=(r for file,secs in printed.items() for r in printed_singles(secs,allowed[file]))
    locations=set()
    for row in itertools.chain(exams['items'],extra):
        file=row['file']
        if file not in allowed or row['pic'] or row['ocr']:continue
        head=clean(row['head']);qtype=row['qtype'];raw=row['text']
        if qtype not in ('语音辨音','字母','不同类','单项选择','情景交际','适当形式','翻译','连词成句','句型转换','首字母填空','汉语提示填词'):continue
        if '听' in head or DEPEND.search(head+raw) or re.search(r'根据.{0,8}(?:短文|表格|信息|文章)|连线|左右栏|阅读|读短文|方框|匹配|\[表\]|#{2}|见上|下列材料',head+raw):continue
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
        if re.search(r'(?:^|\s|[（(]\s*[）)]\s*)\d+[.．](?!\d)',raw[LEADING.match(raw).end():]):continue
        if qtype=='语音辨音' and not re.search('发音|读音|拼读|音标',head):continue
        if qtype=='字母' and not re.search('大小写|顺序|字母表|相邻|左邻右舍',head):continue
        location=(file,head,no)
        if location in locations:continue
        locations.add(location)
        rows[row['id']]=dict(id=row['id'],source=real_pool.format_src(allowed[file],row.get('tag','')),file=file,grade=row['grade'],
            head=SECTION.sub('',head).strip(),stem=stem,options=opts,key=key,qtype=qtype,no=no,topics=row['topics'])
        if SECTION.match(head):rows[row['id']]['section']=SECTION.match(head)[1]
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
    for file,secs in printed.items():
        for q in recovered_groups(secs,allowed[file],paired.get(file,{})):
            rows[q['id']]=q
    return index_units(rows,units,lessons)


def keyed_grammar(target,q):
    """Use the verified form the pupil supplies, including full answers to word-order tasks."""
    t=norm(target)
    qt=q['qtype']
    if qt not in ('连词成句','句型转换','适当形式','单项选择'):return False
    key=norm(q['key']).strip()
    stem=norm(q['stem'])
    ordered=qt=='连词成句' and len(key.split())>=2
    # Reordering tests the printed sentence itself. For a fill-in, require evidence at its blank.
    question='?' in (key if ordered else stem) or '？' in stem
    sentence=key if ordered else stem.replace('______',key,1)
    if qt=='句型转换' and 'to be' in t and 'yes/no' in t and re.search('改为一般疑问句|改成一般疑问句',stem):
        opening=re.match(r'(?:is|are|am) (?:it|she|he|they|we|you|this|that|these|those)\b',key)
        if opening and 'past' not in t:
            return ('plural' not in t or key.startswith('are ')) and ('singular' not in t or not key.startswith('are '))
    if 'to be' in t:
        past='past' in t
        verb=r'was|were' if past else r'am|is|are'
        if not ordered and not re.fullmatch(verb,key):return False
        if ('questions' in t)!=question:return False
        if 'wh-' in t and not re.search(r'\b(?:what|who|where|how)\b',sentence):return False
        if 'yes/no' in t and re.search(r'^(?:—\s*)?(?:what|who|where|how)\b',sentence):return False
        if re.search(r"\bthere\b|\bgoing to\b|\b(?:am|is|are|was|were) (?:not )?\w+ing\b",sentence):return False
        if 'plural' in t and not re.search(r'\b(?:are|were)\b',sentence):return False
        if 'singular' in t and not re.search(r'\b(?:am|is|was)\b',sentence):return False
        return bool(re.search(r'\b(?:'+verb+r')\b',sentence))
    if 'present progressive' in t:
        if ('questions' in t)!=question and ':' in t:return False
        return bool(re.search(r'\b(?:am|is|are)\s+(?:not\s+)?\w+ing\b|\b(?:is|are) (?:he|she|they|it|you|we) \w+ing\b',sentence)
                    and (ordered or re.fullmatch(r'(?:(?:am|is|are) )?\w+ing|am|is|are',key)))
    if 'past simple' in t and ('regular' in t):
        if ('questions' in t)!=question:return False
        if not ordered and qt not in ('适当形式','单项选择'):return False
        if re.search(r"\b(?:has|have|had|is|are|was|were|been|'s)\s+\w+ed\b|(?:'s|'re) \w+ed\b",sentence):return False
        past_words=r'went|took|ate|bought|made|saw|gave|got|wrote|rode|came|ran|brought|did|flew|had|felt|found|lost|met|knew|told|became|left|spent|kept|sang|swam|won|sat|built|sent|drank'
        if question and key in ('did',"didn't"):return False  # the auxiliary alone does not identify the verb class
        if 'irregular' in t:test=past_words
        else:test=r'(?:visit|enjoy|cheer|work|climb|walk|watch|count|travel|travell|talk|play|help|wash|clean|cook|stay|look|want|need|start|finish|ask|jump|listen|open|turn|call|land|return|plant|paint|pick)ed|(?:past|shar|lik|lov|mov|us|liv|danc|arriv|chang|clos)ed|studied|tried|carried|stopped|planned'
        if ordered:return bool(re.search(r'\b(?:'+test+r')\b',key) and re.search(r'\b(?:i|we|they|he|she|you|it)\s+(?:'+test+r')\b',key))
        return bool(re.fullmatch(test,key) and (qt=='适当形式' or any(norm(o) in stem or re.search(r'\b(?:yesterday|last|ago)\b',stem) for o in q['options'])))
    if t=='a/an':return not ordered and key in ('a','an') and bool(re.search(r'_{2,}\s+\w+',stem))
    if 'preposition' in t:
        if ordered:return False
        if 'time' in t:
            return key in ('in','on','at') and bool(re.search(r'_{2,}\s+(?:\d|(?:mon|tues|wednes|thurs|fri|satur|sun)day|(?:the )?(?:morning|afternoon|evening)|night|noon|spring|summer|autumn|winter)',stem))
        return key in ('under','behind','beside','between','above','near','in front of','next to') and bool(re.search(r'_{2,}\s+\w+',stem))
    if 'possessive adjectives' in t:
        return not ordered and key in ('my','your','his','her','its','our','their') and bool(re.search(r'_{2,}\s+\w+',stem))
    if 'demonstrative pronouns' in t:return not ordered and key in ('these','those','this','that') and re.search(r'_{2,}\s+(?:is|are)\b',stem)
    if 'possessive pronouns' in t:return not ordered and key in ('mine','ours','yours','hers','theirs')
    if 'adverbs of frequency' in t:
        return key in ('always','usually','sometimes','never','often') or ordered and re.search(r'\b(?:always|usually|sometimes|never|often)\b',key)
    if 'commands' in t and qt=='单项选择':
        return (key in ("don't",'do not') and 'negative' in t and re.match(r'^_*\s*_{2,}\s+\w+',stem)) or ('negative' not in t and
                re.fullmatch(r'look|listen|open|close|put|stand|sit|come|go|touch|show|point|wave|turn|take',key) and
                re.match(r'^(?:please )?_{2,}\s+(?:at|to|your|the|up|down)\b',stem))
    if 'commands' in t and ordered:
        return bool(re.match(r"(?:please |don't )?(?:look|listen|open|close|put|stand|sit|come|go|touch|show|point|wave|turn|take|be)\b",key) and ("don't" in key)==('negative' in t))
    if 'can' in t and 'permission' not in t and ('can’t' in target or "can't" in t):
        return bool(ordered and re.search(r"\bcan(?:not|'t)?\b",key) or key in ("can","can't") and re.search(r'_{2,}\s+(?:play|swim|dance|sing|run|cook|do|help|draw|speak)\b',stem))
    if 'like' in t or 'want' in t or t.startswith(('have, has','present simple: have')):
        if 'question' in t and not question:return False
        forms=r'likes?|like' if 'like' in t else r'wants?|needs?' if 'want' in t else r'have|has'
        return bool(re.fullmatch(forms,key) or ordered and re.search(r'\b(?:'+forms+r')\b',key))
    if 'how much' in t:
        return ordered and re.match(r'how (?:many|much)\b',key)
    if 'subject and object pronouns' in t:
        return qt=='适当形式' and key in ('he','him','she','her','they','them','i','me','we','us') and re.search(r'[(（](?:i|me|we|us|he|him|she|her|they|them)[)）]',stem)
    if 'comparative' in t or 'superlative' in t:
        # Require an adjective (rather than a noun in -er or a verb in -est).
        adjectives=r'bigg|small|tall|short|long|young|old|fast|slow|strong|weak|high|low|larg|nic|cheap|warm|cold|hot(t)?|cool|hard|light|dark|clos'
        ending=r'er' if 'comparative' in t else 'est'
        return bool(re.search(r'\b(?:'+adjectives+r')'+ending+r'\b',key) and ('than' in sentence if ending=='er' else 'the ' in sentence))
    if 'should for' in t:return bool(ordered and re.search(r"\bshould(?:n't)?\b",key))
    if 'there is, there are' in t and ordered:return bool(re.search(r'\bthere (?:is|are)\b',key))
    return False


def spelling_word(q):
    # Join the original printed fragments with the checked missing letters for indexing.
    m=re.fullmatch(r'([a-z_ ]+?)\s*[（(][\u4e00-\u9fff]+[)）]',q['stem'].replace('　',' '),re.I)
    if not m or '_' not in m[1]:return ''
    blanks=re.split(r'(_+)',m[1])
    letters=re.split(r'\s*[;；]\s*',q['key'])
    if len(letters)==1 and len(letters[0])==len(blanks[1::2]):letters=list(letters[0])
    if len(letters)!=len(blanks[1::2]) or not all(re.fullmatch('[a-zA-Z]+',v) for v in letters):return ''
    blanks[1::2]=letters
    return ''.join(blanks).replace(' ','').lower()


def matches_grammar(g,q):
    target=norm(g['name'])
    if keyed_grammar(target,q):return True
    if 'past simple regular verbs' in target and norm(q['key']) in ('need','red','bed','seed','speed','feed'):return False
    if 'present progressive' in target:
        return grammar_matches(target,g['zh'],q) and bool(re.search(r"\bing\b|\b\w+ing\b|^(?:am|is|are)$",norm(q['key'])))
    return grammar_matches(target,g['zh'],q) or advanced_grammar(target,q)


def dialogue_patterns(card):
    """Concrete sentence forms, because broad invitation/greeting tags span unrelated units."""
    rules={
        'G0-U1':r"my name(?: is|'s)|i(?: am|'m) .{0,12}(?:years old|from)|how old are you",
        'G0-U2':r"(?:is this|can i (?:use|borrow)|where is) (?:your|my|his|her)",
        'G0-U3':r"let's (?:buy|play)|(?:please|don't) (?:play|touch|open|take)|i(?:'d| would) like (?:a|to buy)",
        'G0-U4':r"where (?:is|are)|is (?:this|that|it) (?:a |your |my )",
        'G0-U5':r"(?:what|where|who) are (?:they|these|those)|are (?:they|these|those) ",
        'G0-U6':r"what can (?:you|he|she)|can you (?:play|sing|dance|swim|run|ride|draw)",
        'G0-U7':r"do you like|i (?:like|don't like) (?:to eat|eating|apples|fruit|rice|milk)",
        'G0-U8':r"what (?:do you|does .+?) (?:usually |often )?do|when do you|what time do you",
        'G0-U9':r"what (?:is|are) .{1,16} doing|(?:is|are) (?:he|she|they|you) (?:wearing|playing|making|doing)",
        'G1-U1':r"who(?:'s| is) (?:this|that|he|she)|is (?:this|that|she|he) your",
        'G1-U2':r"(?:this|that) is (?:my|our|his|her|your)|are (?:these|those) (?:your|my)",
        'G1-U3':r"(?:there (?:is|are)|(?:is|are) there) (?:a |an |any |some )",
        'G1-U4':r"what do you (?:do|like)|do you (?:often|usually|play)|does (?:she|he) ",
        'G1-U5':r"do you like|what (?:do you|does he|does she) like|whose .{1,18} is",
        'G1-U6':r"do you have|does (?:he|she) have|what .{0,12}do you have",
        'G1-U7':r"can you (?:play|sing|dance|swim|run|draw)|(?:can i have|i'd like) some",
        'G1-U8':r"what do you (?:want|need)|do you (?:want|need)|would you like to come",
        'G1-U9':r"what (?:is|are) .{1,16} doing|(?:is|are) (?:he|she|they|you) (?:wearing|playing|making|doing)",
        'G2-U1':r"how (?:can|do) i (?:get|go)|turn (?:left|right)|(?:next to|in front of|between) (?:the|a)",
        'G2-U2':r"how often|i (?:usually|often|sometimes|never)",
        'G2-U3':r"how (?:much|many)|(?:do you have|are there|is there) any",
        'G2-U4':r"how was|where (?:was|were)|were you|was (?:he|it|she)",
        'G2-U5':r"what did you|where did you|whose .{1,20}(?:is|are)|(?:i|we) (?:went|saw|took) ",
        'G2-U6':r"(?:i|we|he|she|they) (?:visited|played|walked|looked|watched|helped|talked|stayed)|did you (?:visit|play|walk|watch|help|stay)",
        'G2-U7':r"what did you|where did you|(?:i|we) (?:went|saw|took|bought) ",
        'G2-U8':r"(?:taller|shorter|older|bigger|smaller|faster|stronger) than|the (?:tallest|shortest|biggest|strongest)|call (?:for help|the police)",
        'G2-U9':r"you should|should i|(?:may|can) i (?:use|borrow|go|take)",
    }
    return re.compile(r'\b(?:'+rules[card['id']]+r')\b',re.I) if card['id'] in rules else None


def index_units(rows,units,lessons):
    routes={}; used=set()
    for card in units['units']:
        if card['level'] not in CONFIG['grades']:continue
        scopes=lessons['levels'][card['level']][card['unit']]['sessions']
        core=(w for s in scopes if s['id'] in ('S1','S2','S3','S7') for w in s['words'])
        wordset={form for w in itertools.chain(core,card['vocab']['words']) for form in forms(norm(w))}-STOP
        theme={v for zh,english in THEMES.items() if zh in card['theme'] for w in english.split() for v in forms(w)}
        ph=card['phonics']
        grammar={t for g in card['grammar'] for t in g['topics']}
        sentence_pattern=dialogue_patterns(card)
        fn=set(card['pragmatics']['topics'])
        goals=card['pragmatics']['zh']+' '+card['pragmatics']['en']
        unit={b:{} for b in CONFIG['counts'] if b!='phonics' or card['level'] in ('G0','G1')}
        for id,q in rows.items():
            if q['grade'] not in CONFIG['grades'][card['level']]:continue
            qt=q['qtype'];topics=set(q['topics'])
            text=q['stem']+' '+' '.join(q['options'])+' '+' '.join(p['stem'] for p in q.get('parts',[]))
            if 'parts' in q:
                text+=' '+' '.join(p['key'] for p in q['parts'] if p['options'])
            words=tokens(text); hits=wordset & (words | tokens(q.get('key','')))
            hits.update(w for w in wordset if ' ' in w and re.search(r'\b'+re.escape(w)+r'\b',norm(text)))
            if qt=='汉语提示填词':
                spelled=spelling_word(q)
                if spelled:words.add(spelled);hits.update(wordset & {spelled})
            theme_hits=theme & words
            matches={}
            if 'parts' in q:
                block='reading' if qt=='阅读理解' else 'dialogue'
                cnt=len(re.findall(r"[a-z]+(?:'[a-z]+)?",q['stem'],re.I))
                if block=='reading' and card['level'] in ('G0','G1') and not 15<=cnt<=65:continue
                if block=='dialogue' and ((sentence_pattern.search(norm(text)) if sentence_pattern else topics & ((grammar|fn)-{'fn.dialogue','sy.yes_no','sy.basic_patterns'})) or any(re.search(a,goals,re.I) and re.search(b,text,re.I) for a,b in FUNCTIONS)):
                    matches[block]=2
                elif len(theme_hits)>=2 or hits-keywords('good new school have happy great nice'):matches[block]=1
            elif qt in ('语音辨音','字母'):
                marked=set(map(norm,re.findall(r'<u>(.*?)</u>',text,re.I)))
                patterns=tokens(ph['rule'])-set('initial ending sounds long short sound vowels consonants blends and the alphabet hard soft controlled diphthongs'.split())
                rule=ph['rule'].lower()
                focus=marked & patterns
                if 'initial' in rule:focus={m for m in focus if re.search(r'(?<![a-z])<u>'+re.escape(m)+r'</u>',text,re.I)}
                if 'ending' in rule or 'end sounds' in rule:focus={m for m in focus if re.search(r'<u>'+re.escape(m)+r'</u>(?![a-z])',text,re.I)}
                if rule.startswith('short '):
                    vowel=rule[-1]
                    ipa={'a':'æ','i':'ɪ','o':'ɒ','e':'e','u':'ʌ'}.get(vowel)
                    samples={'a':'cat bat bag map hat man sad','i':'sit pig big pin fish ship six',
                             'o':'hot dog box fox pot top','e':'bed pen ten hen leg red desk',
                             'u':'cup sun nut cut run bus hut'}
                    printed_words=re.findall(r'[a-z]*<u>[a-z]+</u>[a-z]*',norm(text))
                    focus=(ipa and '/'+ipa+'/' in text or any('<u>'+vowel+'</u>' in w and
                           TAGS.sub('',w) in samples.get(vowel,'').split() for w in printed_words))
                if 'phonics' in unit and (focus or qt=='字母' and 'alphabet' in rule):
                    matches['phonics']=2
            else:
                if any(matches_grammar(g,q) for g in card['grammar']):
                    matches['grammar']=2
                elif topics & grammar and qt in ('适当形式','句型转换','连词成句') and any(g['name'].lower() in ('present simple','tense review') for g in card['grammar']):
                    matches['grammar']=1
                lexical_hits=hits | theme_hits
                # Adjective pairs such as excited/exciting test the unit word's meaning in context.
                cue=re.search(r'[（(]\s*([a-z]+)\s*[)）]',norm(q['stem']))
                if qt=='适当形式' and cue and cue[1] in wordset and re.fullmatch(r'[a-z]+',norm(q['key'])):
                    root=cue[1].removesuffix('ed').removesuffix('ing')
                    if {cue[1],norm(q['key'])}=={root+'ed',root+'ing'}:matches['vocab']=2
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
