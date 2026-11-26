const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const read=name=>fs.readFileSync(path.join(root,name),'utf8');
const ctx=vm.createContext({window:{},TextEncoder,Blob});
const {execFileSync}=require('node:child_process');
const bank=JSON.parse(execFileSync('python3',['-c',"import sys,json;sys.path.insert(0,'scripts');from kb import teacher_bank;print(json.dumps(teacher_bank()))"],{cwd:root,maxBuffer:8*1024*1024}));
const hw=vm.runInContext(read('app/cpp-homework.js').replace(/initHomework\(\);\s*$/,'Homework'),ctx);
const out=vm.runInContext(read('app/homework-export.js')+'\nHomeworkExport',ctx);

test('public grade matrix, fixed structure, verified answer, and deduplication for 36 units',()=>{
  assert.equal(Object.keys(bank.routes).length,36);
  assert.deepEqual(JSON.parse(JSON.stringify(bank.config.grades)),{G0:[3,4,5],G1:[3,4,5],G2:[4,5,6],G3:[5,6,7]});
  for(const [unit,route] of Object.entries(bank.routes)){
    for(const block of [null,...Object.keys(route)]){
      for(const [t,tier] of hw.tiers.entries()){
        const p=hw.create(bank,unit,block,tier);
        assert.equal(p.grade,bank.config.grades[unit.slice(0,2)][t]);
        const goal=p.sections.reduce((n,s)=>n+s.goal,0);
        assert.equal(goal,block?10:/^G[01]/.test(unit)?20:18);
        const seen=new Set();
        for(const s of p.sections){
          assert.ok(s.ids.length<=s.goal);
          for(const id of s.ids){
            const q=bank.items[id];
            assert.equal(q.grade,p.grade);assert.ok(route[s.block][id]);
            const fingerprint=hw.identity(q);assert.ok(!seen.has(fingerprint));seen.add(fingerprint);
            if(s.block==='dialogue')assert.equal(q.parts.length,5);
            if(s.block==='reading')assert.ok(q.parts.length && q.stem);
            if(q.parts)assert.ok(q.parts.every(sub=>sub.key));else assert.ok(q.key);
          }
        }
      }
    }
  }
  for(const q of Object.values(bank.items)){
    assert.ok(fs.existsSync(path.join(root,'corpus',q.file)));
    assert.doesNotMatch(q.file,/内部|Unit Test/i);
    assert.doesNotMatch(q.head+' '+q.stem,/\d+\s*分[）)]|得分[:：]|满分[:：]|\[图\]/);
  }
});

test('swap, top-up, reroll, and an empty pool retain their grade and scope',()=>{
  const p=hw.create(bank,'G0-U1','vocab','L');
  const s=p.sections[0],before=hw.exposure(bank,p);
  assert.equal(s.ids.length,10);
  assert.ok(hw.edit(bank,p,s,'swap',1,before));assert.equal(s.ids.length,10);
  const previous=hw.exposure(bank,p);
  const newPaper=hw.create(bank,'G0-U1','vocab','L',p);
  assert.ok(newPaper.sections[0].ids.every(id=>!previous.has(hw.identity(bank.items[id]))));
  hw.edit(bank,p,s,'delete',0,before);assert.equal(s.ids.length,9);
  assert.ok(hw.edit(bank,p,s,'add',0,before));assert.equal(s.ids.length,10);
  const empty=hw.create({...bank,routes:{'G2-U9':{vocab:{}}}},'G2-U9','vocab','H');
  assert.equal(empty.sections[0].ids.length,0);
  assert.match(out.lines(bank,p,false)[1].text,/姓名.*班级.*日期/);
  assert.equal(out.lines(bank,p,true)[0].text,'教师参考答案');
  assert.doesNotMatch(out.lines(bank,p,false).map(x=>x.text).join('\n'),/教师参考答案|满分|得分|答案待核/);
});

test('printed reading subtasks, dialogue blanks and phonics pairs have their own answer keys',()=>{
  const items=Object.values(bank.items);
  const unit3=items.filter(q=>q.file.startsWith('三年级上/03_') && q.parts && q.section);
  const dialogue=unit3.find(q=>q.section==='七');
  assert.match(dialogue.stem,/Mike: Good morning/);
  assert.deepEqual(dialogue.parts.map(p=>p.key),['E','D','B','C','A']);
  const reading=unit3.find(q=>q.section==='八');
  assert.deepEqual(reading.parts.map(p=>p.key),['eyes','toy dog','toys']);
  const pairs=Object.keys(bank.routes['G1-U9'].phonics).map(id=>bank.items[id])
    .filter(q=>q.file.startsWith('四年级上/10_'));
  assert.deepEqual(pairs.map(q=>[q.no,q.key]).sort(),[[4,'√'],[5,'√']]);
  assert.ok(pairs.every(q=>!/[（(]\s*[）)]\s*\d+[.．]/.test(q.stem)));
});

test('dual-tagged originals leave enough distinct questions for both sections',()=>{
  const items=Object.fromEntries(['shared','alternative'].map(id=>[id,{stem:id,options:[],grade:3}]));
  const sample={config:{grades:{G0:[3,4,5]},counts:{vocab:1,grammar:1}},
    items,routes:{'G0-U1':{vocab:{shared:2},grammar:{shared:5,alternative:1}}}};
  const p=hw.create(sample,'G0-U1',null,'L');
  assert.deepEqual([...p.sections[0].ids],['shared']);
  assert.deepEqual([...p.sections[1].ids],['alternative']);
});

test('short clothing reading preserves the common options and the printed subtask answers',()=>{
  const items=Object.keys(bank.routes['G1-U9'].reading).map(id=>bank.items[id]);
  const reading=items.find(q=>q.file.startsWith('A+全程练考卷-4年级/19_') && q.section==='八');
  assert.ok(reading.stem.startsWith('This blue coat is'));
  assert.deepEqual(reading.parts.map(p=>p.key),['the pink socks','the white dress','the orange sweater','the purple skirt']);
  assert.ok(reading.parts.every(p=>p.options.length===4));
  const gradeFivePast=Object.keys(bank.routes['G2-U6'].grammar).map(id=>bank.items[id]).filter(q=>q.grade===5);
  assert.ok(gradeFivePast.every(q=>q.key!=='You need to listen to your friends.'));
});
