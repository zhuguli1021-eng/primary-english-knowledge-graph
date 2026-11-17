#!/usr/bin/env python3
"""Incremental local source intake. Never invent answers or promote OCR to approved questions.
python3 scripts/import_sources.py <source-dir> --ocr-bin .local/intake/ocr_pdf --workers 3
State/raw text live under ignored .local/intake; portable catalog/evidence under data/.
"""
import argparse, concurrent.futures, hashlib, json, re, subprocess, threading
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
from pypdf import PdfReader
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parent.parent
LOCK=threading.Lock()

def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=1)+'\n');tmp.replace(p)

def scope(name):
    if any(x in name.upper() for x in ['IELTS','FCE','雅思']):return 'advanced',None
    if '中考' in name:return 'secondary',9
    if any(x in name for x in ['七上','7上','初一']):return 'secondary',7
    if '月考' in name:return 'secondary',None
    m=re.search(r'([3-6])\s*[上下]',name)
    if m:return 'primary',int(m.group(1))
    for char,g in [('三',3),('四',4),('五',5),('六',6)]:
        if char+'年级' in name or char+'上' in name or char+'下' in name or str(g)+'年级' in name:return 'primary',g
    return 'primary',7

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def run(args):
    source=Path(args.source).resolve()
    if not source.is_dir():raise FileNotFoundError('试题库目录不存在，请先挂载硬盘：'+str(source))
    local=ROOT/'.local/intake';local.mkdir(parents=True,exist_ok=True)
    state_path=local/'manifest.json';old=json.loads(state_path.read_text()) if state_path.exists() else {'files':{}}
    entries={};seen={};jobs=[]
    for p in sorted(source.rglob('*')):
        if p.is_symlink() or not p.is_file() or p.name.startswith('.') or '__MACOSX' in p.parts:continue
        rel=p.relative_to(source).as_posix();sc,g=scope(rel);ext=p.suffix.lower();st=p.stat();prev=old['files'].get(rel,{})
        doc=ext in ['.pdf','.docx','.doc','.txt','.jpg','.png','.jpeg','.xlsx']
        sha=prev.get('sha256') if prev.get('size')==st.st_size and prev.get('mtime_ns')==st.st_mtime_ns else None
        if doc and not sha:sha=digest(p)
        entry={'path':rel,'size':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':sha,'scope':sc,'grade':g,'status':'catalogued'}
        if sha and sha in seen:entry.update(status='duplicate',duplicate_of=seen[sha])
        else:
            if sha:seen[sha]=rel
            eligible=sc=='primary' and ext in ['.pdf','.docx','.doc','.txt','.jpg','.png','.jpeg']
            if eligible:
                entry['status']='pending'
                if sha==prev.get('sha256'):
                    for key in ('status','pages','extracted_pages','unclear_pages'):
                        if key in prev:entry[key]=prev[key]
                jobs.append((p,entry))
            elif sc!='primary':entry['status']='outside_primary'
            else:entry['status']='asset_only'
        entries[rel]=entry
    state={'source_root':str(source),'files':entries};save(state_path,state)
    print('Catalogued',len(entries),'files;',len(jobs),'primary documents/images; duplicate',sum(e['status']=='duplicate' for e in entries.values()),flush=True)
    if not args.scan:
        ocr=str(Path(args.ocr_bin).resolve()) if args.ocr_bin else None
        def process(job):
            p,e=job;cache=local/'text'/e['sha256'];cache.mkdir(parents=True,exist_ok=True)
            try:
                cached=cache/'0001.json'
                if p.suffix.lower()!='.pdf' and cached.exists() and (not args.retry_empty or json.loads(cached.read_text()).get('text','').strip()):
                    e.update(status='extracted_pending_review',pages=1,extracted_pages=1,unclear_pages=[] if json.loads(cached.read_text()).get('text','').strip() else [1])
                    return
                if p.suffix.lower()=='.pdf':
                    reader=PdfReader(p);n=len(reader.pages);e['pages']=n
                    for i,pg in enumerate(reader.pages,1):
                        dest=cache/f'{i:04}.json'
                        if dest.exists():
                            if not args.retry_empty or json.loads(dest.read_text()).get('text','').strip():continue
                        text=pg.extract_text() or '';method='pdf_text'
                        if len(re.findall('[A-Za-z一-鿿]',text))<100:
                            if not ocr:raise RuntimeError('OCR executable required')
                            raw=subprocess.run([ocr,str(p),str(i),str(i)],capture_output=True,text=True,check=True,timeout=180).stdout
                            text='\n'.join(re.sub(r'^\d\.\d+ \d\.\d+ ','',x) for x in raw.splitlines() if not x.startswith('=== page'));method='vision_ocr'
                        save(dest,{'page':i,'method':method,'text':text,'needs_review':not bool(text.strip()),'review':'pending_teacher'})
                        if i%20==0:print(e['path'],i,'/',n,flush=True)
                else:
                    if p.suffix.lower()=='.docx':
                        with zipfile.ZipFile(p) as z:tree=ET.fromstring(z.read('word/document.xml'))
                        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                        text='\n'.join(''.join(t.itertext()) for t in tree.findall('.//w:p',ns));method='docx_text'
                    elif p.suffix.lower()=='.doc':text=subprocess.run(['textutil','-convert','txt','-stdout',str(p)],capture_output=True,text=True,check=True,timeout=60).stdout;method='doc_text'
                    elif p.suffix.lower()=='.txt':text=p.read_text(errors='replace');method='text'
                    else:
                        if not ocr:raise RuntimeError('OCR executable required')
                        text=subprocess.run([ocr,str(p)],capture_output=True,text=True,check=True,timeout=180).stdout;method='vision_ocr'
                        text='\n'.join(re.sub(r'^\d\.\d+ \d\.\d+ ','',x) for x in text.splitlines() if not x.startswith('=== page'))
                    if not text.strip():raise RuntimeError('No extracted text')
                    save(cache/'0001.json',{'page':1,'method':method,'text':text,'needs_review':not bool(text.strip()),'review':'pending_teacher'});e['pages']=1
                e['status']='extracted_pending_review';e['extracted_pages']=len(list(cache.glob('*.json')))
                e['unclear_pages']=[json.loads(f.read_text())['page'] for f in sorted(cache.glob('*.json')) if not json.loads(f.read_text()).get('text','').strip()]
                print('DONE',e['path'],e['extracted_pages'],flush=True)
            except Exception as ex:e['status']='error';e['error']=str(ex)[:400];e['extracted_pages']=len(list(cache.glob('*.json')));print('ERROR',e['path'],str(ex)[:120],flush=True)
            finally:
                with LOCK:save(state_path,state)
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:list(pool.map(process,jobs))
    # Only elementary-stage evidence is exposed to elementary homework; no answer-key-only files.
    topics=json.loads((ROOT/'data/topics.json').read_text());refs={t['id']:[] for t in topics};snippets=set()
    for e in entries.values():
        if e['status']!='extracted_pending_review' or any(x in Path(e['path']).stem for x in ['答案','解析']):continue
        for f in sorted((local/'text'/e['sha256']).glob('*.json')):
            page=json.loads(f.read_text());lines=[re.sub(r'\s+',' ',s).strip() for s in page['text'].splitlines()]
            for t in topics:
                if t['grade']>e['grade']:continue
                sig=[re.compile(s,re.I) for s in t['signals']]
                candidates=[s for s in lines if 20<len(s)<240 and re.search('[A-Za-z]{3}',s) and any(r.search(s) for r in sig) and (re.search(r'_{2,}|\b[A-D][.．]',s) or t['id'].startswith(('rd.','wr.','fn.')))]
                for line in candidates[:1]:
                    key=(t['id'],re.sub(r'\W','',line).lower())
                    if key in snippets:continue
                    snippets.add(key)
                    # At most two per source/topic, with multiple source documents preserved.
                    if sum(r['sourceId']==e['sha256'] for r in refs[t['id']])>=2:break
                    refs[t['id']].append({'id':'import:'+e['sha256'][:16]+':p'+str(page['page'])+':'+t['id'], 'text':line,'source':e['path'], 'sourceId':e['sha256'],'page':page['page'],'grade':e['grade'],'review':'OCR/信号匹配待教师核对','method':page['method']})
    catalog={'version':1,'updated':datetime.now(timezone.utc).isoformat(),'counts':dict(Counter(e['status'] for e in entries.values())),
      'files':[{k:v for k,v in e.items() if k not in ['mtime_ns','error']} for e in entries.values()],
      'note':'文件数不等于试卷份数或可用题数；OCR/信号匹配未经教师核对，不进入已审核题库。高级别资料不用于小学作业。'}
    save(ROOT/'data/source_catalog.json',catalog);save(ROOT/'data/exam_references.json',{'version':1,'topics':refs,'note':catalog['note']})
    print('FINISHED',catalog['counts'],'evidence',sum(map(len,refs.values())),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('source');ap.add_argument('--ocr-bin');ap.add_argument('--workers',type=int,default=3);ap.add_argument('--scan',action='store_true');ap.add_argument('--retry-empty',action='store_true');run(ap.parse_args())
