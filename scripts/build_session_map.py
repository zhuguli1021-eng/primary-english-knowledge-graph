"""Build the offline CPP lesson index from an exported target card and two workbooks."""
import argparse
import json
import re
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://dujuanhmily-d4gdrdvsua1435cf7-1498606100.tcloudbaseapp.com/4nt9cxpqec/'

def split_words(text):
    return [w.strip() for w in re.split(r'[、,，;；\n]', text or '') if w.strip() not in ('', '—', '无', '0')]

def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace('‐', '-').replace('’', "'")).strip()

def alignment(sheet):
    rows = list(sheet.values)
    vocab = next(row for row in rows if 'Vocabulary' in str(row[0]))
    result = {}
    for col, header in enumerate(rows[2]):
        header = str(header)
        if '年级' in header and header[0] in '三四五六七八九':
            grade = '三四五六七八九'.index(header[0]) + 3
        elif '高一' in header or '高二' in header:
            grade = 10 if '高一' in header else 11
        else:
            continue
        for word in split_words(vocab[col]):
            result.setdefault(normalize(word), set()).add(grade)
    return {w: sorted(gs) for w, gs in result.items()}

def extract(cards, quant, align, graph):
    levels = {}
    sheets = {name: list(quant[name].values) for name in ('拼读', '语法点详细整理', 'Writing主题和语法点', '阅读主题', 'Sheet2')}
    for level in range(7):
        lv = f'G{level}'
        grades = alignment(align[lv])
        lessons = {}
        for number in range(1, 10):
            key = f'{lv}|U{number}'
            raw = cards['units'][key]
            unit = graph[key.replace('|','-')]
            phonics = raw['ph']
            word_sets = raw['vo']
            texts = raw['tx']
            columns = 2 * number - 1
            writing = sheets['Writing主题和语法点'][3 + level]
            grammar_col = [1, 3, 6, 8, 10, 12, 14][level]
            quantized = {
                'theme': sheets['阅读主题'][3 + level][columns + 1],
                'grammar': sheets['语法点详细整理'][number][grammar_col],
                'phonics': sheets['拼读'][2 + level][number],
                'writing': writing[columns],
                'writingFocus': writing[columns + 1],
                'listening': sheets['Sheet2'][2 + level][number],
            }
            sessions = []
            assert [s['课次'] for s in raw['sess']] == [f'S{i}' for i in range(1,16)]
            for num, source in enumerate(raw['sess'],1):
                sid = source['课次']
                row = {'id':sid,'name':source['教材课次'],'pages':source['学生书页码'],'focus':source['本课次教材内容'].strip()}
                group = {1:1,2:2,3:3,7:4}.get(num)
                words = split_words(word_sets.get(f'Key Words {group}')) if group else []
                category = 'reading'
                if num in (1,7):
                    category='vocab'
                if num in (4,12):
                    category='grammar'
                    grammar=next(g for g in raw['gr'] if g['课次']==sid)
                    row['target']=grammar['语法点（教材原名）']
                    row['use']=grammar.get('用来表达什么（教研归纳）','')
                elif num==5:
                    category='phonics'
                    words=split_words(phonics.get('练习词（录音脚本）'))
                    row['target']=phonics['本单元语音／拼写规则']
                elif num==6:
                    category='writing'
                elif num in (13,14,15):
                    category={13:'oracy',14:'mission',15:'project'}[num]
                    if num==14: words=split_words(raw['pr'].get('任务词'))
                    row['cue']=raw['pr'].get('提示卡句子','') if num==13 else ''
                if num in (1,2,3,7,8,9,10,11):
                    text=texts[0 if num<7 else 1]
                    row['text']=text['标题／任务']
                    row['strategy']=text.get('阅读策略／写作要点','')
                    row['textPages']=text['学生书页']
                    # Some cards abbreviate the end incorrectly (e.g. p172–19).
                    # Use the actual text span to select only the assigned half.
                    page_numbers=[int(n) for n in re.findall(r'\d+',text['学生书页'])]
                    numbers=[int(n) for n in re.findall(r'\d+',row['pages'])]
                    if len(numbers)==2 and numbers[1]<numbers[0]:
                        if num in (2,9,10) and len(page_numbers)==2 and page_numbers[1]>=numbers[0]:
                            end=min(numbers[0]+1,page_numbers[1])
                            row['pages']=f'p{numbers[0]}–{end}'
                        else: row['pages']=f'p{numbers[0]} 起'
                    first,last=(page_numbers+[0,0])[:2]
                    if num in (9,10):
                        nums=re.findall(r'\d+',row['pages']);first,last=int(nums[0]),int(nums[-1])
                    questions=[]
                    for line in raw['li'].get('思维品质·课文 Think 问题','').splitlines():
                        match=re.match(r'.*?p(\d+)\s+(.+)',line)
                        if match and first<=int(match[1])<=last:questions.append(match[2].strip())
                    row['think']=questions[:2]
                if re.search(r'p(\d+)–(\d+)',row['pages']):
                    m=re.search(r'p(\d+)–(\d+)',row['pages'])
                    if int(m[2])<int(m[1]):
                        start=int(m[1])
                        evidence=[int(a[0][1:]) for a in raw['acts'] if a[1]==sid and re.fullmatch(r'p[0-9]+',a[0])]
                        row['pages']=f'p{start}–{max(evidence)}' if evidence and max(evidence)>start else f'p{start} 起'
                if num==13:
                    listen=next((t for t in texts if t['文本']=='听力'),{})
                    row['audioTitle']=listen.get('标题／任务','本课听力')
                    row['audioPages']=listen.get('学生书页',row['pages'])
                row['category']=category
                if words:row['words']=words
                if category=='grammar':topics=unit['grammar'][0 if num==4 else 1]['topics']
                elif category in ('oracy','mission'):topics=unit['pragmatics']['topics']
                elif category=='project':topics=unit['writing']['topics']
                else:topics=unit[category]['topics']
                if category=='phonics' and unit['id'] in ('G0-U2','G0-U5','G0-U6','G0-U7','G0-U8','G0-U9'):
                    topics=['ph.letters','ph.same_sound']
                row['topics']=list(dict.fromkeys(topics + (unit['vocab']['topics'] if words and category=='reading' else [])))
                sessions.append(row)
            known_words={normalize(w) for s in sessions for w in s.get('words',[])}
            lessons[f'U{number}']={'quantified':quantized,'sessions':sessions,
                                    'wordGrades':{w:grades[w] for w in sorted(known_words) if w in grades}}
        levels[lv]=lessons
    return {'source':SOURCE,'workbooks':['【VICIN】剑桥path教材知识量化表','开心口袋 G0–G6 对标表 v2'],'levels':levels}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('cards','quant','alignment'):parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    graph={u['id']:u for u in json.loads((ROOT/'data/cpp_units.json').read_text())['units']}
    wb=lambda path:load_workbook(path,read_only=True,data_only=True)
    data=extract(json.loads(args.cards.read_text()),wb(args.quant),wb(args.alignment),graph)
    (ROOT/'data/cpp_sessions.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
