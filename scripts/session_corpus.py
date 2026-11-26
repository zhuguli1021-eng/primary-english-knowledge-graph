"""Build the CPP lesson-to-source index. Keep original paper instructions and source positions."""
import re
from collections import defaultdict
from hashlib import md5

import corpus
import real_pool

TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")
STOP = set("a an the i am is are be was were it this that these those by in of for from on into to so as he she we they us our my you your his her them and or but with at how what when who why where can could should would do does did has have had may will about tell write writing how talk talking say speaking process learn improve task oracy discussion mission learn use using working things something different make making about story text word words learn english science steam art cue card cards yes no all not any some very more than like one two three book read".split())
DEPENDENT = re.compile(r'录音|听音|听力|图片|看图|图示|图中|图意|下图|配图|如图|上图|插图|信息卡|表格|家谱|菜单|示意图|短文|读.{0,2}对话|根据.{0,5}(文章|材料|图|内容)|方框|选项中.{0,5}选.{0,5}答语|左右栏|连线|匹配|\[图\]|【图|见图|picture (?:above|below)|according to the (?:picture|table)', re.I)
TAGS = re.compile(r'</?u>', re.I)
LEADING = re.compile(r'^\s*(?:[（(]\s*[)）]\s*)?(\d{1,3})\s*[.．、]\s*')
NOISY = re.compile(r'#{2}|答案[：:]|解析[：:]|听力部分|笔试部分|[|]|(?:\n|　)[（(]\s*[）)]\s*\d+[.．]|\n\s*\d+[.．]\s*[A-Za-z]|\[图\]')
GROUP_PHONICS = re.compile(r'(?:字母|组合).{0,3}(?:发音|读音)|发音|读音', re.I)


def norm(s):
    return ' '.join(s.lower().replace('’',"'").replace('‐','-').split())


def tokens(s):
    return set(TOKEN.findall(norm(TAGS.sub('',s))))


def forms(word):
    if ' ' in word or len(word)<4:
        return {word}
    root = word[:-3]+'y' if word.endswith('ies') else word[:-1] if word.endswith('s') and not word.endswith(('ss','us','is')) else word
    return {root, word, root+'s'}


def keywords(text):
    return {v for w in tokens(text)-STOP if len(w)>2 for v in forms(w)}


# Worked reference answers for frequently used starter questions whose scans lack a paired key.
# The stored values are answer text, so a corrected source or reordered options stays detectable.
STARTER_KEYS = {
    'R45a2be5e':'green', 'Rc3e4b57c':'colour', 'Re031aa69':'mum', 'Rbbe71dbf':'bear',
    'R6ae08eb6':'brown', 'Rc25e5bd3':'brown', 'R38cf2f6c':'这里也有一个游乐场。',
    'R02b9d403':'There is a playground.',
    **dict.fromkeys('R0195f54f R853507df R0ddcaa78 Rfffd0bff R8acee92f R2cd7ec78 Re4b21243 Rfdc7ebbb Re0b2000f R5618167a Racc3d312'.split(),'an'),
    **dict.fromkeys(['Rfd187682','R7c1627dc'],'a'),
    **dict.fromkeys('R9274b86b R42ebce7f Re1b17a75 R6ced62f9 R862aa3c2'.split(),'My'),
    **dict.fromkeys('Rcce9aa24 Raea3d1c2 R8ef5e2c9'.split(),'your'),
    'R4ec555cb':'my',
    **dict.fromkeys('R371914bc R5d951758 R1b99a49a R2f8c0a81 Rd3c9db52 R92872b9f R0d0f718e R48ef82b2 R6cfb4724 R6b74db99 R4243a580 R967cf752 R73e421fc Ra1213f1d R7523b763'.split(),'is'),
    'R35d729ae':'am','R3be93587':'am','R2c492931':'are',
}


def original_singles(items, pool, papers):
    sources={p['file']:p for p in papers}
    keys = {}
    for q in pool['singles']:
        if q['answerVerified']:
            keys[(q['stem'],tuple(tuple(c) for c in q.get('choices',[])),pool['sources'][q['si']])]=q['answer']
    for row in items:
        head, text = row['head'], row['text']
        if row['pic'] or row['ocr'] or DEPENDENT.search(head+' '+text) or NOISY.search(text) or len(text)>490:
            continue
        number = LEADING.match(text)
        if not number or row['file'] not in sources:
            continue
        body=corpus.TAG.sub('',text[number.end():]).strip()
        body=re.sub(r'^[（(]\s*[)）]\s*','',body)
        options=real_pool.OPT_SPLIT.split(body)
        stem=options[0].strip()
        choices=list(zip(options[1::2],map(str.strip,options[2::2])))
        if len({norm(v) for _,v in choices})!=len(choices):continue
        if choices and ([a for a,_ in choices]!=list('ABCD'[:len(choices)]) or len(choices)<2 or
                        any(not v or re.search(r'(?:^|\s)E[.．]|\n\s*[一二三四五六七八九十]、',v) for _,v in choices)):
            continue
        if not body or ('画线' in head or '划线' in head) and not re.search(r'<u>.+?</u>',body,re.I):
            continue
        if re.search(r'填.{0,3}序号|选择.*答语|选.*句子',head) and not choices and row['qtype']!='连词成句':
            continue
        qtype=row['qtype']
        if '不同类' in head or '同一类' in head or '不属于同类' in head:
            qtype='词语分类'
        if qtype not in ('单项选择','适当形式','句型转换','情景交际','不同类','词语分类','连词成句','翻译','汉语提示填词','首字母填空','语音辨音','字母'):
            continue
        if qtype in ('单项选择','情景交际') and not choices:
            continue
        if qtype in ('翻译','句型转换') and not choices and not re.search(r'翻译|汉译英|英译汉|译成|改为|改成|同义|提问',head+stem):
            continue
        if qtype=='语音辨音' and not GROUP_PHONICS.search(head):
            qtype='词语分类' if '同类' in head else '词义选择'
        if qtype=='字母' and not re.search('大小写|字母顺序|字母表',head):
            continue
        if choices and re.search(r'I see a _+ bear|It.s a _+ bear',stem,re.I):
            continue
        source=real_pool.format_src(sources[row['file']],row.get('tag',''))
        ans=keys.get((stem,tuple(choices),source))
        if choices:
            ans=next((v for letter,v in choices if letter==ans),None)
        elif ans:
            ans=' / '.join(ans)
            if re.fullmatch(r'[A-G](?:\s*/\s*[A-G])*',ans):
                ans=None
        question=dict(id=row['id'], file=row['file'], source=source, grade=row['grade'],
                      kind='真题' if row.get('tag') else row['kind'], head=head, no=number[1], stem=stem,
                      options=[v for _,v in choices], qtype=qtype)
        if ans:
            question['key']=ans
        if row['id'] in STARTER_KEYS and not ans:
            key=STARTER_KEYS[row['id']]
            if not choices or key in question['options']:
                question.update(key=key,reviewed=True)
        yield question


def original_blocks(pool, papers):
    # The pool's stable passage and writing IDs include their corpus file path.
    files=defaultdict(list)
    for paper in papers:
        files[real_pool.format_src(paper)].append(paper['file'])
    for gr in pool['groups']:
        if gr['qtype']!='阅读理解' or NOISY.search(gr['passage']) or '_' in gr['passage'] or re.search('根据.{0,5}图|如图|见图',gr['passage']):
            continue
        src=pool['sources'][gr['si']]
        file=next((f for f in files[src] if 'RP'+md5((f+gr['passage'][:120]).encode()).hexdigest()[:8]==gr['id']),None)
        if not file:
            continue
        for i,q in enumerate(gr['questions']):
            if NOISY.search(q['stem']) or DEPENDENT.search(q['stem']) or len(q['stem'])<5 or any(NOISY.search(v) for _,v in q['choices']):
                continue
            result=dict(id=gr['id']+'-'+str(i+1),group=gr['id'],source=src,file=file,grade=gr['grade'],kind=gr['kind'],
                        head=q['qtype'],no=str(i+1),stem=q['stem'],options=[v for _,v in q['choices']],qtype='阅读理解',
                        passage=gr['passage'],topic=q['topic'])
            if q['answerVerified']:
                result['key']=dict(q['choices']).get(q['answer'])
            yield result
    for w in pool['writings']:
        if DEPENDENT.search(w['stem']) or NOISY.search(w['stem']) or re.search(r'如下|以下信息|图片|根据提示词|图表',w['stem']):
            continue
        src=pool['sources'][w['si']]
        file=next((f for f in files[src] if 'RW'+md5((f+w['stem'][:100]).encode()).hexdigest()[:8]==w['id']),None)
        if file:
            yield dict(id=w['id'],file=file,source=src,grade=w['grade'],kind=w['kind'],head='书面表达',no='',
                       stem=w['stem'],title=w['title'],options=[],qtype='书面表达')

# A question must test the form in its answer slot. Merely mentioning a grammar
# word elsewhere in a sentence (the original topic tagger's signal) is insufficient.
def grammar_matches(target, use, q):
    if q['qtype'] not in ('单项选择','适当形式','句型转换','连词成句'):
        return False
    t=norm(target)
    stem=norm(q['stem'])
    opts={norm(v).strip('.!?') for v in q['options']}
    choices=' '.join(sorted(opts))
    blank=r'_{2,}'
    past=r'(?:yesterday|last (?:week|month|year|night|sunday|summer)|ago)'
    regular=r'\b\w+ed\b'
    irregular=r'\b(?:went|took|ate|bought|made|saw|gave|got|wrote|rode|came|ran|brought|did|flew|had)\b'
    def slot(rx):
        return bool(re.search(rx.replace('~',blank),stem))
    def options(rx):
        return sum(bool(re.fullmatch(rx,v)) for v in opts)>=2
    def text(rx):
        return bool(re.search(rx,stem))
    question='?' in stem or '？' in stem
    if 'a/an'==t:
        return 'a' in opts and 'an' in opts and options(r'a|an|the|/|some')
    if 'possessive adjectives' in t:
        return slot(r'~\s*(?:name|arm|family|eyes?|bird|garden|father|mother|book|desk|friend|coat|hair|brother|teacher|parents?|home|school|pen|hands?|shoes?|room|sister|bag|pencils?|dog|cat)\b') and bool(opts & set('my your his her its our their'.split())) and options(r'my|your|his|her|its|our|their|i|we|you|he|she|me|us|they|mine|ours|hers|him|them|yours')
    if 'possessive pronouns' in t:
        return bool(opts & {'mine','ours','yours','hers','theirs'}) and slot(r'~\s*[.?!。]|~\s*$')
    if 'reflexive' in t:
        return options(r'\w+(?:self|selves)')
    if 'demonstrative' in t:
        return options('this|that|these|those')
    if 'subject and object pronouns' in t:
        return options(r'he|him|she|her|they|them|we|us|i|me') and not slot(r'~\s+(?:name|mother|father|book|brother|sister)')
    if 'possessive' in t and "'s" in t:
        return any(v.endswith("'s") and v[:-2] in opts for v in opts)
    if 'there is, there are' in t:
        return slot(r'\bthere\s+~|~\s+there\b') and options(r'is|am|are|was|were|be')
    if 'to be' in t or t.startswith('verb to be'):
        ispast='past' in t
        if not (options('was|were|is|are|am') or slot(r'~\s*[（(]be[)）]')):
            return False
        if ispast!=bool(text(past) or opts & {'was','were'} and not opts & {'is','are','am'}):
            return False
        if text(r'there |\w+ing\b') or ('questions' in t)!=question or ('wh-' in t)!=bool(re.match(r'(?:—\s*)?(?:what|who|where|how)\b',stem)):
            return False
        if 'plural' in t and not text(r'\b(?:they|these|those|we)\b'):
            return False
        return not ('singular' in t and text(r'\b(?:they|these|those|we)\b'))
    if 'prepositions of time' in t:
        return options('on|at|in|by|for') and slot(r'~\s*(?:[0-9]|monday|tuesday|friday|sunday|january|the morning|night|noon)')
    if 'preposition' in t:
        return options(r'in|on|at|under|above|behind|beside|between|near|in front of|next to') and slot(r'~\s*(?:the |a |his |my |her |your )') and not text('morning|week|afternoon|sunday')
    if 'adverbs of frequency' in t:
        return options('always|usually|often|sometimes|seldom|never')
    if 'how much' in t:
        return options('much|many|how many|how much') or slot(r'how\s+~') and opts & {'many','much'}
    if 'quantifier' in t or 'countable and uncountable' in t:
        return options(r'(?:a )?few|(?:a )?little|much|many|some|any|lots of|a lot of|a|an') and bool(opts & {'few','little','many','much','some','any','a lot of'})
    if 'indefinite pronouns' in t:
        return options(r'(?:any|some|no|every)(?:thing|body|one)')
    if 'compar' in t or 'superlative' in t:
        if 'adverb' in t and not re.search('ly|faster|harder',choices):
            return False
        return (('superlative' in t and text('of all|one of the|among|the _') and re.search(r'\b(?:\w+est|most|best)\b',choices)) or
                ('compar' in t and text(r'\bthan\b') and (re.search(r'\b(?:\w+er|more|better)\b',choices) or slot(r'~\s*[（(]'))))
    if 'past simple' in t or 'past tense with ago' in t:
        if 'passive' in t or 'perfect' in t: return False
        if ('questions' in t)!=question or not text(past) or 'ago' in t and not text('ago'): return False
        if question: return slot(r'~\s+(?:you|he|she|they)|\bdid\b[^.?!]{0,28}~')
        return bool(re.search(irregular if 'irregular' in t else regular if 'regular' in t else irregular+'|'+regular,choices)) or slot(r'~\s*[（(][a-z]+[)）]') and 'regular' not in t
    if 'progressive' in t or 'interrupted past' in t:
        if 'perfect' in t or 'future' in t: return False
        ispast='past' in t
        if ispast and not text('when|while|last night|at that time'): return False
        if ('questions' in t)!=question: return False
        return bool(slot(r'(?:am|is|are|was|were)\b[^.?!]{0,24}~') and re.search(r'ing\b',choices) or
                    options(r'am|is|are|were|was') and slot(r'~\s+(?:\w+\s+)?\w+ing\b')) and (ispast or not text('was|were|last night'))
    if t in ('will','future plans with going to'):
        return slot(r'(?:will|going to)\s+~|~\s+going to|~\s+to\s+\w+') and ('going' in stem+choices if 'going to' in t else 'will' in stem)
    if 'simple' in t and 'present' in t or t.startswith(('like /','yes/no questions with like','have, has')):
        if 'passive' in t or 'future' in t: return False
        specific=next((v for v in ('like','want','have') if v in t),'')
        if specific and not re.search(r'\b'+({'have':'(?:have|has)','like':'likes?','want':'(?:wants?|needs?)'}[specific])+r'\b',stem+' '+choices):return False
        if specific=='have' and not question: return options('have|has|having')
        if 'negative' in t and not ('don\'t' in stem+choices or "doesn't" in stem+choices): return False
        if 'questions' in t and not question:return False
        if 'affirmative' in t and question:return False
        return options("do|does|don't|doesn't") or bool(any(v+'s' in opts or v+'es' in opts for v in opts) and not text(past))
    if 'commands' in t:
        return slot(r"(?:please|don't)\s+~") and ("don't" in stem)==('negative' in t)
    if any(k in t for k in ('can','could','should','may','must','have to','had to','might')):
        if any(k in t for k in ('deduction','future','have and','had to','could have')):return False
        verbs=set(re.findall(r'\b(?:can|could|must|should|might|may)\b',t))
        if not verbs: return False
        if 'permission' in t and not question:return False
        if 'when' in t and 'when' not in stem:return False
        return any(slot(r'\b'+v+r"(?:n't)?(?:\s+(?:you|i|she|he|they|we))?\s+~") for v in verbs)
    return False

# Useful contrasts in the upper CPP books that also occur in entrance papers.
def advanced_grammar(target, q):
    if q['qtype'] not in ('单项选择','适当形式','句型转换'):
        return False
    target=norm(target)
    stem=norm(q['stem'])
    opts=' | '.join(norm(v) for v in q['options'])
    if 'passive' in target:
        if 'future' in target: return bool(re.search(r'will be \w+(?:ed|en|wn|lt|ld)\b',opts))
        if 'perfect' in target:return 'had been' in opts
        verb=r'\b(?:is|are|was|were) (?:\w+(?:ed|en)|made|built|held|sold|taught|given|taken|grown)\b'
        return bool(re.search(verb,opts) and ('past' not in target or re.search(r'\b(?:was|were) ',opts)) and
                    ('present' not in target or re.search(r'\b(?:is|are) ',opts)))
    if 'present perfect' in target:
        if 'progressive' in target:return bool(re.search(r'(?:have|has) been \w+ing',opts))
        context=next((m for k,m in [('ever','ever|never'),('already','already|yet|just'),('how long','how long'),('since','for|since')] if k in target),None)
        form=bool(re.search(r'\b(?:have|has) (?:\w+(?:ed|en)|been|seen|gone|done|had|read)\b',opts)) or bool(re.search(r'(?:have|has)\b.{0,30}____',stem))
        return form and (bool(re.search(r'\b(?:'+context+r')\b',stem+' '+opts)) if context else '?' in stem)
    if 'relative' in target:
        words=set(opts.split(' | '))
        needed={'who','whose'} if 'whose' in target else {'that','where'} if 'where' in target else {'who','which','that','whose','where'}
        return bool(len(words & {'who','which','that','whose','where','whom'})>=2 and words & needed
                    and not re.search(r'\b(?:know|tell me|wonder|asked)\b',stem) and
                    re.search(r'\b(?:person|girl|boy|man|woman|book|one|place|people|friend|city|park|teacher)\s+_+',stem)
                    and ('non-defining' not in target or ', _' in stem))
    if 'reported' in target or 'embedded questions' in target:
        return bool(re.search(r'(?:asked|told me|tell me|do you know|wonder)\b.{0,18}_+',stem) and
                    re.search('where |when |how |what |why |if |whether ',opts) and
                    ('statements' not in target or 'questions' in target))
    if 'condition' in target:
        if not re.search(r'\bif\b',stem):return False
        if 'third' in target:return 'would have' in opts
        if 'second' in target:return 'would ' in opts
        if 'first' in target:return 'will ' in opts
        return False
    if 'infinitive' in target or 'gerund' in target:
        if 'as subjects' in target and not stem.startswith('_'):return False
        return bool(re.search(r'\b(?:decided?|wants?|hopes?|plan(?:s|ned)?)\s+_+',stem) and 'to ' in opts) if 'infinitive' in target else bool(re.search(r'\b(?:enjoys?|finish(?:ed)?|mind)\s+_+',stem) and 'ing' in opts)
    if 'tag questions' in target:return bool(re.search(r',\s*_+[?？]',stem) and re.search(r"(?:n't|not) (?:he|she|you|they|we|it)",opts))
    if 'used to' in target:return bool(re.search(r'\bused to\s+_+',stem))
    if 'too and enough' in target:return 'too' in opts and 'enough' in opts and ' to ' in stem
    if 'past perfect' in target:return bool(re.search(r'\b(?:before|by the time)\b',stem) and re.search(r'\bhad (?:\w+ed|been|gone|left|done)',opts))
    return False


FUNCTIONS = [
    (r'asking for directions|问路',r'问路|怎么去|how (?:can|do) i (?:get|go)|which way'),
    (r'borrowing|借用',r'借.{0,4}(?:笔|书|尺)|(?:can|may|could) i (?:borrow|use)'),
    (r'introduc|介绍自己|说明自己的身份',r'自我介绍|介绍自己|别人.{0,6}名字|my name is'),
    (r'shopping|buying groceries|购物|购买食品',r'买东西|购物|how much (?:is|are)|can i help you'),
    (r'giving advice|give advice|给.{0,4}建议',r'给.{0,6}建议|you should|you.d better'),
    (r'giving opinions|stating opinions|giving reasons|i think because',r'what do you think of|in my opinion|你认为|你的看法'),
    (r'asking for help|请求帮助',r'请求帮助|请.{0,4}帮助|can you help|could you help'),
    (r'positive feedback|夸奖',r'夸奖|称赞|表扬|well done|good job'),
    (r'agreeing|disagreeing|i agree|do you agree',r'你同意|表示同意|不同意|i agree|i disagree'),
    (r'clarif|active listening|repeat that',r'没有听清|没听清|再说一遍|repeat that|say that again'),
    (r'describ.{0,8} routine|描述.{0,3}作息',r'what time do you|when do you (?:get up|go to bed)'),
]


def writing_skill(focus,q):
    t=norm(focus)
    stem=norm(q['stem'])
    if q['qtype']=='连词成句':
        if 'complete sentences' in t or 'write statements' in t:return '完整句书写'
        if 'question' in t and ('?' in stem or '？' in stem):return '疑问句书写'
        if 'exclamation' in t and '!' in stem:return '感叹句书写'
        if 'conjunction' in t and re.search(r'\b(?:and|but|because|or)\b',stem):return '连词运用'
        if 'because' in t and 'because' in stem:return '原因表达'
        if 'adverbs' in t and re.search(r'\b(?:quickly|slowly|carefully|usually|always)\b',stem):return '在句中使用副词'
        if 'before and after' in t and re.search(r'\b(?:before|after)\b',stem):return '时间连接词'
    if q['qtype']=='句型转换' and 'question' in t and re.search(r'改为.{0,4}疑问句',stem):return '疑问句书写'
    return ''


READING_SKILLS = [
    ('情节|plot|setting|开头|beginning',r'where did|where does|happen|at first|in the end|what happened|main character'),
    ('主题|theme|作出判断|evaluating',r'what can we learn|lesson|main idea|best title'),
    ('比较|异同|compar',r'difference|in common|both|similar|different from'),
    ('主旨|概括|main idea|summar',r'mainly|main idea|best title|best describes'),
    ('因果|cause',r'why|reason|because|as a result'),
    ('顺序|sequence|order',r'order|first|before|after|last|happened next'),
    ('推断|inferen|conclusion',r'infer|probably|most likely|can we learn'),
    ('词义|context',r'mean|closest in meaning|underlined word'),
    ('预测|predict',r'will most likely|happen next|probably'),
    ('人物|感受|character|feelings',r'feel|what.*like|describe|personality'),
    ('作者|purpose',r'author|writer|purpose'),
    ('事实|观点|opinion',r'fact|opinion'),
    ('细节|detail',r'where|when|which|how many|who|what|true'),
]
GENRES = ('letter','email','diary','poem','invitation','recipe','biography','report','brochure','blog','poster','interview','advertisement','news','instructions')
GENRE_ZH = ('信','邮件','日记','诗','邀请','食谱','传记','报告','手册','博客','海报','采访','广告','新闻','说明书')


def prepare(q):
    q['_words']=tokens(q['stem'])
    q['_opts']=tokens(' '.join(q['options']))
    q['_context']=keywords(q.get('passage',q['stem']))
    q['_count']=len(TOKEN.findall(q.get('passage','')+' '+q['stem']+' '+' '.join(q['options'])))
    return q


def build(exams,pool,papers,units,lessons):
    materials={}
    passages={}
    by_grade=defaultdict(list)
    for q in (*original_singles(exams['items'],pool,papers),*original_blocks(pool,papers)):
        prepare(q)
        by_grade[q['grade']].append(q)
    routes={}
    for card in units['units']:
        unit=lessons['levels'][card['level']][card['unit']]
        for s in unit['sessions']:
            cat=s['category']
            vocab={f for w in s.get('words',[]) for f in forms(norm(w))}
            unit_terms=keywords(' '.join(card['vocab']['words']))
            subject=keywords(s.get('text','')+' '+s['focus'].split('\n')[0])
            task=s['focus'].split('\n')[0]
            genres=[(en,zh) for en,zh in zip(GENRES,GENRE_ZH) if re.search(r'\b'+en+r'\b',task,re.I)]
            block_terms=keywords(s.get('text',''))
            strategy=next((pattern for key,pattern in READING_SKILLS if re.search(key,s.get('strategy',''),re.I)),None)
            hits=[]
            for grade in range(max(3,card['grade']-3),min(7,card['grade']+1)+1):
                for q in by_grade[grade]:
                    if grade>card['grade']:
                        limit=120 if q['qtype']=='阅读理解' and card['grade']>=5 else 18
                        if q['_count']>limit or q['qtype']=='书面表达':
                            continue
                    qt=q['qtype']
                    stem=q['stem']
                    match=''
                    if cat=='grammar':
                        if grammar_matches(s['target'],s.get('use',''),q) or advanced_grammar(s['target'],q):
                            match=s['target']
                    elif cat=='phonics':
                        if qt=='字母' and 'Alphabet' in s['target']:match=s['target']
                        if qt=='语音辨音':
                            marks=set(map(norm,re.findall('<u>(.*?)</u>',stem+' '+' '.join(q['options']),re.I)))
                            patterns=tokens(s['target'])-set('initial sounds sound ending spelling short vowel long and silent prefix suffix digraphs blends tip consonant letters rule patterns controlled for or with start vowels diphthongs hard soft'.split())
                            if marks & patterns:match=s['target']
                    elif qt=='阅读理解' and vocab and cat in ('vocab','reading') and (vocab-STOP) & (q['_words'] | q['_opts']):
                        matched=(vocab-STOP) & (q['_words'] | q['_opts'])
                        match='原卷阅读中的课次词汇 · '+', '.join(sorted(matched))
                    elif qt=='阅读理解' and cat=='reading':
                        theme=q['_context'] & unit_terms
                        skill_hit=strategy and re.search(strategy,stem,re.I)
                        if skill_hit or (s['id']!='S8' and (len(theme)>=2 and q['_context'] & block_terms or len(theme)>=4)):
                            match=('阅读策略 · '+s['strategy']) if skill_hit else ('阅读同主题 · '+', '.join(sorted(theme)[:4]))
                    elif qt=='书面表达' and cat in ('writing','project','mission'):
                        genre=next((g for g,zh in genres if g in q['_words'] or zh in stem),None)
                        theme=q['_context'] & subject
                        if genre or len(theme)>=2 or theme & keywords(q['title']) or norm(s.get('text','--')) in norm(stem):
                            match=('写作体裁 · '+genre) if genre else ('任务话题 · '+', '.join(sorted(theme)))
                    elif cat in ('vocab','reading') and vocab and qt not in ('书面表达','阅读理解','字母','语音辨音'):
                        # Translation and word-order items actually require the words in the stem.
                        # For choices, use lexical alternatives, not incidental stem words.
                        lexical=qt in ('不同类','词语分类','词义选择','翻译','连词成句')
                        tested=(q['_words']|q['_opts']) if lexical else tokens(q.get('key','')) if not q['options'] else set()
                        if not lexical and qt=='单项选择' and q['options'] and all(len(tokens(v))==1 for v in q['options']) and not (q['_opts'] & STOP):
                            tested=q['_opts']
                        found=vocab & tested
                        for phrase in (p for p in vocab if ' ' in p):
                            if lexical and re.search(r'\b'+re.escape(phrase)+r'\b',norm(stem+' '+' '.join(q['options']))):found.add(phrase)
                        if found:match='课次词汇 · '+', '.join(sorted(found))
                    elif cat in ('oracy','mission','project','writing') and qt in ('情景交际','翻译','连词成句','句型转换','词语分类'):
                        cue=norm(s.get('cue',''))
                        phrases=[p.strip(' .!?') for p in re.split(r'[.!?…]',cue) if len(tokens(p)-STOP)>=1 and len(tokens(p))>=2]
                        active=(vocab-STOP) | subject
                        words=active & (q['_opts']|q['_words'])
                        if any(p and re.search(r'\b'+re.escape(p)+r'\b',norm(stem+' '+' '.join(q['options']))) for p in phrases):
                            match='交际用语 · '+s['cue']
                        elif len(words)>=2 or words and qt=='情景交际' and words & (vocab-STOP):
                            match='任务用语 · '+', '.join(sorted(words))
                    if not match and cat=='writing':
                        match=writing_skill(task,q)
                    if not match and cat in ('oracy','mission','project') and qt=='情景交际':
                        for aim,language in FUNCTIONS:
                            if re.search(aim,task,re.I) and re.search(language,norm(stem+' '+' '.join(q['options'])),re.I):
                                match='交际任务 · '+task
                                break
                    if match:
                        hits.append((q,match))
            if hits:
                route={}
                for q,match in hits:
                    route[q['id']]=match
                    if q['id'] not in materials:
                        materials[q['id']]={k:v for k,v in q.items() if not k.startswith('_') and k!='passage'}
                        if 'group' in q:
                            passages[q['group']]=q['passage']
                routes[card['id']+'-'+s['id']]=route
    return {'items':materials,'routes':routes,'passages':passages}
