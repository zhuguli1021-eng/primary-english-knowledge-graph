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

test('all 945 lesson placements produce three scoped, scored worksheets',()=>{
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
        assert.equal(paper.sections.length,3);
        const qs=paper.sections.flatMap(p=>p.qs);
        assert.equal(qs.reduce((n,q)=>n+q.points,0),paper.total);
        assert.ok(qs.every(q=>q.sessionKey===unit.id+'-'+session.id && q.key && q.stem && q.lines>0));
        assert.ok(qs.every(q=>q.skill && q.topicIds.length && q.topicIds.every(id=>session.topics.includes(id))));
        assert.doesNotMatch(JSON.stringify(qs),/undefined|\[object Object\]/);
        for(const q of qs) if(q.options.length){
          assert.equal(q.options.length,new Set(q.options).size);
          assert.ok(q.options.includes(q.key));
        }
        signatures.add(qs.map(q=>q.stem).join(' '));
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
