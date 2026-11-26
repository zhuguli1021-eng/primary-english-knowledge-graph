// Run with node --test tests/session-homework.test.cjs.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname,'..');
const context = vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(root,'app/data.js'),'utf8'),context);
const kb=context.window.KB;
context.KB=kb;
context.CPP=kb.cpp_units;
context.shuffle=values=>[...values].reverse();
const program=fs.readFileSync(path.join(root,'app/cpp-homework.js'),'utf8');
vm.runInContext(program.replace(/\binitHomework\(\);\s*$/,''),context);

test('all 945 lesson placements produce scoped, scored worksheets at three levels',()=>{
  const known=new Set(kb.topics.map(t=>t.id));
  assert.equal(kb.cpp_units.units.length,63);
  for(const unit of kb.cpp_units.units){
    const book=kb.cpp_sessions.levels[unit.level][unit.unit];
    assert.equal(book.sessions.length,15);
    for(const [i,session] of book.sessions.entries()){
      assert.equal(session.id,'S'+(i+1));
      assert.ok(session.topics.length>0 && session.topics.every(k=>known.has(k)));
      const signatures=new Set();
      for(const level of ['L','M','H']){
        const paper=context.makeSessionPaper(unit.id,session.id,level);
        assert.equal(paper.level,level);
        assert.ok(paper.sections.length>=1 && paper.sections.length<=3,unit.id+' '+session.id);
        const qs=paper.sections.flatMap(p=>p.qs);
        assert.equal(qs.reduce((n,q)=>n+q.points,0),paper.total);
        assert.ok(qs.every(q=>q.sessionKey===unit.id+'-'+session.id && q.key && q.stem && q.lines>0));
        assert.ok(qs.every(q=>q.skill && q.topicIds.length && q.topicIds.every(id=>session.topics.includes(id))));
        assert.doesNotMatch(JSON.stringify(qs),/undefined|\[object Object\]/);
        for(const q of qs) if(q.options.length){
          assert.equal(q.options.length,new Set(q.options).size);
          if(!q.sourceItem || q.sourceItem.key) assert.ok(q.options.includes(q.key));
        }
        signatures.add(paper.minutes);
      }
      assert.equal(signatures.size,3,unit.id+' '+session.id);
    }
  }
});
test('G0 U2 has separate article, phonics and possessive lessons',()=>{
  const book=kb.cpp_sessions.levels.G0.U2;
  assert.equal(book.sessions[3].target,'a/an');
  assert.match(book.sessions[4].target,/Initial Sounds/);
  assert.equal(book.sessions[11].target,'Possessive Adjectives');
  assert.ok(book.wordGrades.desk.includes(4));
  assert.match(context.makeSessionPaper('G0-U2','S13','L').instructions,/音频/);
  assert.throws(()=>context.makeSessionPaper('G0-U2','S16','M'));
});

test('corpus questions can be traced to the source file, lesson and original answer status',()=>{
  const items=kb.cpp_corpus.items, routes=kb.cpp_corpus.routes;
  const corpusData=JSON.parse(fs.readFileSync(path.join(root,'data/exam_items.json'),'utf8'));
  const sourceItems=new Map(corpusData.items.map(q=>[q.id,q]));
  const pool=kb.real_pool;
  const passages=new Map(pool.groups.map(g=>[g.id,g]));
  const writings=new Map(pool.writings.map(w=>[w.id,w]));
  for(const [id,item] of Object.entries(items)){
    if(item.group){
      const group=passages.get(item.group);
      assert.equal(kb.cpp_corpus.passages[item.group],group.passage);
      assert.ok(group.questions.some(q=>q.stem===item.stem));
    } else if(writings.has(id)){
      assert.equal(item.stem,writings.get(id).stem);
    } else {
      const raw=sourceItems.get(id);
      assert.equal(raw.file,item.file,id);
      assert.ok(raw.text.includes(item.stem),id);
      assert.ok(item.options.every(v=>raw.text.includes(v)),id);
    }
    assert.ok(fs.existsSync(path.join(root,'corpus',item.file)),id);
    if(item.group)assert.ok(kb.cpp_corpus.passages[item.group],id);
  }
  for(const sid of ['S1','S4','S12']){
    const paper=context.makeSessionPaper('G0-U2',sid,'M');
    const originals=paper.sections.flatMap(s=>s.qs).filter(q=>q.sourceItem);
    assert.ok(paper.originalCount>=2 && originals.length===paper.originalCount);
    assert.equal(originals.length,new Set(originals.map(q=>q.sourceItem.id)).size);
    for(const q of originals){
      assert.ok(routes['G0-U2-'+sid][q.sourceItem.id]);
      assert.ok(q.stem.includes(q.sourceItem.stem));
      assert.deepEqual(q.options,q.sourceItem.options);
      if(q.sourceItem.key)assert.equal(q.key,q.sourceItem.key);
      else assert.equal(q.keyLabel,'答案待核');
    }
  }
  for(const [route,ids] of Object.entries(routes)){
    const [lv,unit,sid]=route.split('-');
    const paper=context.makeSessionPaper(lv+'-'+unit,sid,'M');
    const qs=paper.sections.flatMap(p=>p.qs);
    assert.ok(paper.originalCount>0,route);
    if(Object.keys(ids).some(id=>items[id].kind==='真题'))assert.ok(paper.realCount>0,route);
    for(const section of paper.sections){
      const group=section.qs.find(q=>q.sourceItem?.group)?.sourceItem.group;
      if(group)assert.equal(section.passage,kb.cpp_corpus.passages[group]);
    }
    assert.ok(qs.every(q=>!q.sourceItem || ids[q.sourceItem.id]));
  }
  const [missing]=kb.cpp_units.units.flatMap(u=>kb.cpp_sessions.levels[u.level][u.unit].sessions
    .filter(s=>!routes[u.id+'-'+s.id]).map(s=>[u.id,s.id]));
  assert.equal(context.makeSessionPaper(...missing,'M').originalCount,0);
});
