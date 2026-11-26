"""Editorial limits for the CPP teacher entry. School grade is provenance, not reading age."""
import re

from kb import FUNCTION, candidates

# A sentence limit applies to the options and subquestions too. Total includes the whole task.
PROFILES = {
    'G0': dict(ages='5–6', sentence=6, single=16, group=48, passage=20, unknown=0),
    'G1': dict(ages='6–8', sentence=10, single=35, group=120, passage=55, unknown=2),
    'G2': dict(ages='8–10', sentence=15, single=60, group=205, passage=120, unknown=5),
}
WORD = re.compile(r"[a-z]+(?:'[a-z]+)?", re.I)
STARTER = set("""a an the am is are be i you he she it we they my your his her its our their me us them
this that these those what where who how old many much yes no not and or but too to of on at in with
have has do does can like see look go come say play put give get sit stand listen point touch show
hello hi bye goodbye good morning afternoon night nice meet thank thanks please ok let's
name friend boy girl mum mom dad baby family dog cat pet big little small tall short happy sad
red blue yellow green black white brown pink orange one two three four five six seven eight nine ten
here there birthday brother sister apple banana together bye year years mike sarah john amy sam tom ann chen jie wu binbin lily ben jack mary""".split())

def words(text):
    return WORD.findall(re.sub(r'</?u>', '', text.lower().replace('’', "'")))

STORY_NAMES=set('alice mike jack peter amy john sarah mary jim tom bob chen jie wu binbin zhang peng liu jia tingting dongdong kate oliver lily lucy sam ben ann'.split())

def familiar_words(terms):
    basic=set(STARTER)
    for term in terms:
        basic.update(words(term))
    # Contractions and common inflections are still the same taught vocabulary.
    plurals={w+'s' for w in basic if len(w)>1}
    return basic | plurals | set("i'm you're he's she's it's we're they're that's what's where's don't doesn't can't isn't aren't let's name's who's".split())

CONCRETE_GROUPS={
    '颜色':set('red yellow blue green brown black white pink orange purple grey gray'.split()),
    '动物':set('dog cat pig cow bird duck rabbit monkey elephant tiger lion panda fish bear giraffe'.split()),
    '家里的人':set('mum mom dad mother father sister brother grandma grandpa aunt uncle'.split()),
    '数字':set('one two three four five six seven eight nine ten'.split()),
}


def child_prompt(q):
    """Offer a shorter instruction only when the original answer action is unambiguous."""
    head=q['head']
    if 'parts' in q:
        if q['qtype']=='阅读理解':
            if all(p['key'] in ('T','F','√','×') for p in q['parts']):
                marks='T 或 F' if q['parts'][0]['key'] in ('T','F') else '√ 或 ×'
                return '听老师读。对不对？选 '+marks+'。'
            if all(p['options'] for p in q['parts']):return '听老师读，再选答案。'
        if q['qtype'] in ('情景交际','补全对话'):return '听老师读，选一句合适的话。'
        return ''
    if q['qtype']=='字母':
        if re.search('大写|小写|大小写',head) and '_' in q['stem']:return '写出它的大写或小写字母。'
        if '顺序' in head and q['key'] in ('√','×'):return '字母排对了吗？选 √ 或 ×。'
        return ''
    if q['qtype']=='语音辨音':
        if '发音不同' in head and q['options']:return '听一听，哪个画线部分读音不同？'
        if q['key'] in ('√','×') and '相同' in head:return '画线部分读音一样吗？选 √ 或 ×。'
        return ''
    if not q['options'] and q['qtype'] in ('翻译','汉语提示填词') and re.fullmatch(r"[a-zA-Z]+(?: [a-zA-Z]+)?",q['key']) and q['stem'].count('______')==1:
        return '听老师读，说出空格里的词。'
    if not 2<=len(q['options'])<=3:return ''
    if '不同类' in head:
        # Asking for a grammatical category (e.g. tall/big/have) is too abstract here.
        options={v.lower().strip() for v in q['options']}
        for name,members in CONCRETE_GROUPS.items():
            if len(options & members)>=2 and options-members=={q['key'].lower()}:
                return '哪一个不是'+name+'？'
        return ''
    if re.search('画线|划线|同类|相反|错误|不正确',head):return ''
    if re.search('意思|汉语|中文|译文|英文',head):return '选出意思对的一项。'
    if q['qtype']=='单项选择' and '_' in q['stem']:return '空格里选哪一个？'
    return ''

def fits(q,level,known,irregular):
    if level not in PROFILES:return True
    profile=PROFILES[level]
    parts=q.get('parts',[])
    if level=='G0':
        if not child_prompt(q):return False
        # A missing picture or common option bank cannot be supplied by reading the prompt aloud.
        if re.search(r"(?:I see a|It[’']s a) _+ bear|^three _+\s*\.",q['stem'],re.I):return False
        if re.search(r'\b(?:although|unless|would|should|must|yesterday)\b',q['stem'],re.I):return False
        if re.search(r'改为|改写|造句|连词成句|仿写|时态|词性|从句|过去式|比较级|最高级',q['head']):return False
        if not parts and (q['stem'].count('______')>1 or any(len(words(v))>3 for v in q['options'])):return False
    if level=='G0' and re.search(r'写|抄',q['head']) and q['qtype']=='字母' and len(q['key'])!=1:return False
    if level=='G1' and re.search('写一段|写一篇|同义句转换|复合句|从句',q['head']):return False
    if not parts and re.search('连线|连起来|左右栏',q['head']) and not q['options']:return False
    visible=[q['stem'],*q['options']]
    for part in parts:
        visible.extend([part['stem'],*part['options']])
    if level=='G0' and any(len(re.findall(r'[\u4e00-\u9fff]',v))>14 for v in visible):return False
    total=0
    vocabulary=set()
    for field in visible:
        field=re.sub(r'(?:^|\s)[A-G][.．]\s*','\n',field)
        for sentence in re.split(r'[.!?。？！;；\n：:—]+',field):
            terms=words(sentence)
            if len(terms)>profile['sentence']:return False
            total+=len(terms)
            vocabulary.update(terms)
    if total>profile['group' if parts else 'single']:return False
    if q['qtype']=='阅读理解' and len(words(q['stem']))>profile['passage']:return False
    if q['qtype']=='字母':return True
    vocabulary.update(words(q.get('key','')))
    unfamiliar={w for w in vocabulary-known if len(w)>1}
    if level!='G0':
        unfamiliar={w for w in unfamiliar if w not in FUNCTION and w.removesuffix("'s") not in STORY_NAMES
                    and not any(base in known for base in candidates(w.removesuffix("'s"),irregular))}
    return len(unfamiliar)<=profile['unknown']
