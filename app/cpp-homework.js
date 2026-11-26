/* Teachers select a unit once. A paper always stays within one public-school grade. */
const Homework = (() => {
  const names={phonics:'语音 / 拼读',vocab:'词汇',grammar:'语法',dialogue:'情景交际',reading:'阅读理解'};
  const tiers=['L','M','H'], labels=['基础','标准','拔高'];
  const gradeName=g=>g===7?'小升初':'公立'+['','','','三','四','五','六'][g]+'年级';
  const normalize=text=>text.normalize('NFKC').toLowerCase().replace(/<\/?u>|[\s\p{P}]/gu,'');
  function identity(q){
    if(q.parts?.length===5 && q.parts.every(p=>/^第 \d+ 空/.test(p.stem))){
      // Reprints may rename the speakers or relocate the bank on the page.
      const lines=q.stem.split('\n');
      const turns=lines.filter(l=>/^[A-Za-z][A-Za-z ’'-]{0,24}[:：]/.test(l));
      const bank=lines.filter(l=>/^[A-G][.．]/.test(l));
      if(turns.length>=5 && bank.length){
        const opening=turns.map(l=>l.replace(/^[^:：]+[:：]/,'')).join(' ');
        return normalize(bank.join(' '))+'|'+normalize(opening).slice(0,160);
      }
    }
    return normalize(q.stem+' '+(q.options||[]).slice().sort().join(' ')+' '+(q.parts||[]).map(p=>p.stem).join(' '));
  }
  function candidates(bank,paper,section,avoid=new Set()){
    const used=new Set(paper.sections.flatMap(s=>s.ids.map(i=>identity(bank.items[i]))));
    return Object.entries(bank.routes[paper.unit][section.block])
      .filter(([id])=>bank.items[id].grade===paper.grade && !used.has(identity(bank.items[id])))
      .map(([id,priority])=>({id,rank:(avoid.has(identity(bank.items[id]))?0:10)+priority+Math.random()}))
      .sort((a,b)=>b.rank-a.rank);
  }
  function draw(bank,paper,section,count,avoid){
    const options=candidates(bank,paper,section,avoid), seen=new Set();
    const selected=[];
    for(const {id} of options){
      const key=identity(bank.items[id]);
      if(seen.has(key))continue;
      selected.push(id);seen.add(key);
      if(selected.length===count)break;
    }
    return selected;
  }
  function exposure(bank,paper){
    return new Set((paper?.sections||[]).flatMap(s=>s.ids.map(id=>identity(bank.items[id]))));
  }
  function create(bank,unit,special,tier,previous){
    const level=unit.split('-')[0],grade=bank.config.grades[level][tiers.indexOf(tier)];
    const blocks=special?[special]:Object.keys(bank.routes[unit]);
    const sections=blocks.map(block=>({block,goal:special?bank.config.special:bank.config.counts[block],ids:[]}));
    const paper={unit,tier,grade,sections,special};
    const avoid=exposure(bank,previous);
    for(const section of [...sections].sort((a,b)=>Number(b.block==='grammar')-Number(a.block==='grammar'))){
      section.ids=draw(bank,paper,section,section.goal,avoid);
    }
    // A shared grammar/vocabulary item can occupy the only remaining vocabulary slot.
    // Move it only when grammar has an unused replacement of its own.
    const grammar=sections.find(s=>s.block==='grammar'), vocab=sections.find(s=>s.block==='vocab');
    if(grammar && vocab && vocab.ids.length<vocab.goal){
      const byText=new Map(Object.keys(bank.routes[unit].vocab)
        .filter(id=>bank.items[id].grade===grade).map(id=>[identity(bank.items[id]),id]));
      for(const [index,id] of grammar.ids.entries()){
        const shared=byText.get(identity(bank.items[id]));
        if(!shared)continue;
        const [replacement]=draw(bank,paper,grammar,1,avoid);
        if(!replacement)break;
        grammar.ids[index]=replacement;
        vocab.ids.push(shared);
        if(vocab.ids.length===vocab.goal)break;
      }
    }
    return paper;
  }
  function edit(bank,paper,section,action,index,history){
    if(action==='delete'){section.ids.splice(index,1);return true;}
    const [id]=draw(bank,paper,section,1,history);
    if(!id)return false;
    if(action==='swap')section.ids[index]=id;else section.ids.push(id);
    history.add(identity(bank.items[id]));
    return true;
  }
  function title(p){
    const [level,u]=p.unit.split('-');
    return level+' · Unit '+u.slice(1)+' '+(p.special?names[p.special]+'专项练习':'综合练习卷')+'（'+p.tier+'）';
  }
  return {names,tiers,labels,gradeName,identity,create,edit,title,exposure};
})();

async function loadTeacherHomework(){
  if(location.protocol==='file:'){
    await new Promise((resolve,reject)=>{
      const script=document.createElement('script');script.src='../data/teacher-homework.js';
      script.onload=resolve;script.onerror=()=>reject(Error('本机题库尚未打包，请在项目中运行 python3 scripts/kb.py bundle。'));
      document.head.append(script);
    });
    return window.CPP_TEACHER_BANK;
  }
  const response=await fetch('/api/teacher/homework',{credentials:'same-origin',cache:'no-store'});
  if(!response.ok || !response.headers.get('content-type')?.includes('application/json'))
    throw Error('请从机构教师入口登录，或打开本机教师工作副本。');
  return response.json();
}

async function initHomework(){
  const form=$('#unitForm'),grade=$('#hwGrade'),unit=$('#hwUnit'),mode=$('#hwType'),block=$('#hwBlock');
  const result=$('#hwResult'),message=$('#hwMessage'), pref=store.get('cpp.unit-homework.v2',{});
  let bank,papers={},histories={},active='L';
  $('#hwGenerate').disabled=true;
  try{bank=await loadTeacherHomework();}catch(e){message.textContent=e.message;return;}
  const options=rows=>rows.map(([value,text])=>'<option value="'+esc(value)+'">'+esc(text)+'</option>').join('');
  grade.innerHTML=options(Object.keys(bank.config.grades).map(g=>[g,g]));
  if(bank.config.grades[pref.grade])grade.value=pref.grade;
  function fillUnits(){
    unit.innerHTML=options(KB.cpp_units.units.filter(u=>u.level===grade.value).map(u=>[u.id,'Unit '+u.unit.slice(1)+' · '+u.theme]));
    block.innerHTML=options(Object.keys(bank.routes[unit.value]).map(b=>[b,Homework.names[b]]));
  }
  function clear(){
    papers={};histories={};result.replaceChildren();message.textContent='';
    $('#hwBlockField').hidden=mode.value!=='special';
    store.set('cpp.unit-homework.v2',{grade:grade.value,unit:unit.value,mode:mode.value,block:block.value});
  }
  fillUnits();
  if(bank.routes[pref.unit] && pref.unit.startsWith(grade.value+'-'))unit.value=pref.unit;
  if(pref.mode==='special')mode.value='special';
  if(bank.routes[unit.value][pref.block])block.value=pref.block;
  clear();$('#hwGenerate').disabled=false;
  grade.onchange=()=>{fillUnits();clear();};unit.onchange=mode.onchange=block.onchange=clear;
  function generate(tiers){
    for(const t of tiers){
      const p=Homework.create(bank,unit.value,mode.value==='special'?block.value:null,t,papers[t]);
      papers[t]=p;histories[t]=Homework.exposure(bank,p);
    }
    message.textContent='';render();
  }
  form.onsubmit=e=>{e.preventDefault();active='L';generate(Homework.tiers);};
  function btn(action,label,attrs=''){return '<button type="button" class="btn" data-action="'+action+'" '+attrs+'>'+label+'</button>';}
  function body(q){
    const text=safeRich(q.stem);
    const opts=q.options.map((v,i)=>String.fromCharCode(65+i)+'. '+safeRich(v)).join('　');
    return text+(opts?'<div class="hwOptions">'+opts+'</div>':'');
  }
  function render(){
    const p=papers[active];
    const some=p.sections.some(s=>s.ids.length);
    const all=Object.values(papers).some(p=>p.sections.some(s=>s.ids.length));
    const sectionHTML=p.sections.map((s,i)=>{
      const status=s.ids.length<s.goal?'<p class="muted small">当前 '+s.ids.length+' / '+s.goal+' 道</p>':'';
      return '<section><h3>'+('一二三四五'[i])+'、'+Homework.names[s.block]+'</h3>'+status+s.ids.map((id,j)=>{
        const q=bank.items[id],attr='data-s="'+i+'" data-i="'+j+'"';
        return '<div class="q"><b>'+ (j+1)+'.</b> '+safeRich(q.head)+'<div>'+body(q)+'</div>'+
          (q.parts||[]).map((sub,k)=>'<div class="hwPart">（'+(k+1)+'）'+body(sub)+'</div>').join('')+
          '<div class="small muted"><a target="_blank" rel="noopener" href="https://github.com/zhuguli1021-eng/primary-english-knowledge-graph/blob/main/corpus/'+q.file.split('/').map(encodeURIComponent).join('/')+'">'+esc(q.source)+'</a>'+esc(q.no?' · 第 '+q.no+' 题':'')+'</div><div class="row actions">'+btn('swap','换一题',attr)+btn('delete','删除',attr)+'</div></div>';
      }).join('')+btn('add','增加 / 补题','data-s="'+i+'"')+'</section>';
    }).join('');
    const toolbar=Homework.tiers.map((t,i)=>btn('tier',t+' '+Homework.labels[i],'data-tier="'+t+'" aria-pressed="'+(t===active)+'"')).join('');
    const answers=HomeworkExport.lines(bank,p,true).slice(2).map(l=>'<div>'+safeRich(l.text)+'</div>').join('');
    result.innerHTML='<div class="row hwTools">'+toolbar+btn('again','当前卷换一批')+btn('againAll','三套换一批')+'</div>'+
      '<article class="card hwSheet"><h2>'+esc(Homework.title(p))+'</h2><p class="muted">'+Homework.gradeName(p.grade)+'</p>'+
      sectionHTML+'<details><summary>教师参考答案</summary>'+answers+'</details></article>'+
      '<div class="row hwTools">'+['pdf','docx'].map(format=>btn('export','导出本套 '+(format==='pdf'?'PDF':'Word'),'data-format="'+format+'" '+(some?'':'disabled'))+
      btn('batch','三套 '+(format==='pdf'?'PDF':'Word')+' 打包','data-format="'+format+'" '+(all?'':'disabled'))).join('')+'</div>';
  }
  result.onclick=async e=>{
    const b=e.target.closest('button[data-action]');if(!b)return;
    const {action,tier,format}=b.dataset;message.textContent='';
    if(action==='tier'){active=tier;render();return;}
    if(action==='again' || action==='againAll'){generate(action==='again'?[active]:Homework.tiers);return;}
    if(action==='export'||action==='batch'){
      b.disabled=true;
      try{await HomeworkExport.download(bank,action==='export'?[papers[active]]:Homework.tiers.map(t=>papers[t]),format,action==='batch');}
      catch(error){message.textContent='导出失败：'+error.message;}
      finally{b.disabled=false;}
      return;
    }
    const p=papers[active],s=p.sections[Number(b.dataset.s)];
    if(!Homework.edit(bank,p,s,action,Number(b.dataset.i),histories[active]))message.textContent='本板块同年级候选题已用完。';
    render();
  };
}
initHomework();
