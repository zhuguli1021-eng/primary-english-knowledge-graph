/* All selection happens within the chosen target-card session. No model or network is required. */
const homeworkTiers = {
  L: {name:'低 · 基础', minutes:15, sentences:1},
  M: {name:'中 · 标准', minutes:20, sentences:2},
  H: {name:'高 · 提升', minutes:25, sentences:3},
};
const approvedExamples = {
  'G0-U1-S4':['vb.be-01','vb.be-03'], 'G0-U1-S12':['vb.be-02'],
  'G0-U2-S4':['ar.a_an-02','ar.a_an-03'], 'G0-U2-S12':['pr.possessive_adj-01','pr.possessive_adj-02'],
  'G0-U4-S4':['pp.place-01'], 'G0-U9-S4':['te.present_continuous-01','te.present_continuous-02'],
  'G1-U2-S4':['pr.demonstrative-01','pr.demonstrative-02'], 'G1-U2-S12':['pr.possessive_adj-01','pr.possessive_adj-03'],
  'G1-U6-S4':['vb.have-01','vb.have-02'], 'G2-U4-S4':['te.past_be-01','te.past_be-03'],
};

function exercise(stem, key, lines=1, options=[]) { return {stem, key, lines, options}; }
function pickExercise(stem, correct, alternatives) {
  const options = shuffle([...new Set([correct, ...alternatives])]);
  return exercise(stem, correct, 1, options);
}
function openTask(stem, criteria, lines=3) {
  return {...exercise(stem, criteria, lines), open:true};
}
function spellingTask(word, meaning, level) {
  const chars = [...word];
  const positions = chars.map((v,i) => /[a-z]/i.test(v) ? i : -1).filter(i=>i>=0);
  const gaps = level==='L' ? 1 : Math.max(1, Math.ceil(positions.length/3));
  for (const pos of shuffle(positions).slice(0,gaps)) chars[pos]='＿';
  return exercise('根据中文补全单词或短语。' + meaning + '　' + chars.join(''), word);
}
function wordSections(s, unit, items, level) {
  const meanings = items.vocabulary[s.id];
  const known = Object.keys(meanings);
  // Order the taught words by their actual position in the grade crosswalk.
  const gradeOf = word => unit.wordGrades[word.toLowerCase().replaceAll('‐','-')]?.[0];
  const ordered = shuffle(s.words).sort((a,b) => {
    const ga=gradeOf(a), gb=gradeOf(b);
    if (ga==null || gb==null) return (ga==null)-(gb==null);
    return level==='H' ? gb-ga : ga-gb;
  });
  const [first,other] = level==='M' ? known : [...known].sort((a,b)=>{
    const ga=gradeOf(a), gb=gradeOf(b);
    if(ga==null || gb==null)return (ga==null)-(gb==null);
    return level==='H'? gb-ga : ga-gb;
  });
  const distractors = shuffle(s.words.filter(w=>w!==first)).slice(0,2);
  const recognition = level==='L'
    ? pickExercise('选出“'+meanings[first]+'”的英文。',first,distractors)
    : level==='M' ? spellingTask(first,meanings[first],level) : openTask('写出“'+meanings[first]+'”的英文，并在一个有意义的短语中使用它。',first+'；短语需体现该词的含义。',2);
  const application = level==='L'
    ? spellingTask(other,meanings[other],level)
    : level==='M' ? openTask('写出 '+other+' 的中文意思，再用它补充一个例子。',meanings[other]+'；例子须与词义一致。',2)
    : openTask('比较 '+first+' 和 '+other+' 的含义，再各写一个能看出词义的短句。',first+' 表示“'+meanings[first]+'”，'+other+' 表示“'+meanings[other]+'”。两句分别符合词义。');
  const word=ordered.find(w=>!known.includes(w)) || other;
  const production=openTask(level==='L'?'读 '+word+'，用画图、中文或一个英文短语说明它的意思。':
    level==='M'?'用 '+word+' 写一个与本课话题有关的完整句。':
    '以本课话题为背景，用 '+word+' 和另一个本课词写两句有关联的话。',
    '核对单元词表；目标词意义正确，表达与本课话题相符。',level==='L'?2:3);
  recognition.skill='词义与拼写 · '+first;
  application.skill='词汇运用 · '+(level==='H'?first+'、':'')+other;
  production.skill='用词表达 · '+word;
  return [recognition,application,production];
}
function readingPrompt(strategy) {
  const rules=[
    [/比较|对比|similar|compar/i,'找出两个可以比较的人物或事物，分别记录一个相同点和一个不同点。'],
    [/虚实|真实与想象|fantasy|real or/i,'摘出一个细节，判断它在现实中能否发生，并指出判断线索。'],
    [/因果|cause/i,'找出一组原因和结果，用箭头把两者连接起来。'],
    [/顺序|次序|sequence|ordering/i,'把两件事按先后排列，并标出帮助你判断顺序的词或细节。'],
    [/预测|predict/i,'先写一个预测，再指出标题、插图或开头给你的线索。'],
    [/主旨|概括|main idea|summar/i,'用自己的话概括主要内容，找出一条支持它的细节。'],
    [/感受|情绪|角色|人物|character/i,'选一个人物，记录一句话或一个动作，并说明它表现了什么特点。'],
    [/事实|观点|opinion/i,'摘录一个陈述，判断它是事实还是观点，说明依据。'],
    [/作者|purpose|point of view/i,'判断作者想向读者说明什么，并指出一处支持你判断的表达。'],
    [/推断|inference|conclusion/i,'写出文中没有直接说明、但能从细节推出的一条信息，并列出依据。'],
    [/语境|词义|context/i,'找出一个有挑战的词，根据前后文写出可能的意思并圈出线索。'],
    [/监控|澄清|monitor|clarif|重读|reread/i,'选一句需要重读的话。写下你的疑问和重读后弄清的一点。'],
  ];
  return rules.find(([pattern])=>pattern.test(strategy))?.[1] ||
    '运用“'+strategy+'”整理这部分内容，写下你从中得到的一条信息和依据。';
}
function grammarSections(s, unitId, items, level) {
  const frame=items.grammar[s.id], m=frame.match(/\[([^\]]+)\]/);
  const [right,wrong,another]=m[1].split('/');
  const complete=frame.replace(m[0],right);
  const first=level==='L'?pickExercise('选择正确形式。'+frame.replace(m[0],'______'),right,[wrong,another]):
    level==='M'?exercise('补全句子。'+frame.replace(m[0],'______')+'（按本课规则填写）',complete+'；符合语境和本课规则的等义表达也可。',2):
    exercise('改正句中的一处错误，并说明理由。'+frame.replace(m[0],wrong),complete+'　依据：'+s.target,2);
  const candidate=(approvedExamples[unitId+'-'+s.id] || []).map(id=>KB.questions.find(q=>q.id===id)).find(q=>q && q.difficulty==='LMH'.indexOf(level)+1);
  const second=candidate?{...exercise(candidate.stem,candidate.choices.find(([k])=>k===candidate.answer)[1],1,candidate.choices.map(v=>v[1])),bankId:candidate.id}:
    openTask(level==='L'?'仿照第 1 题，换一个人、事物或动作，写出一个新例句。':
      level==='M'?'把第 1 题的表达放进一个新情境。写一句铺垫，再写一句使用本课语法的话。':
      '另设一个能用到本课语法的情境。写一个正确例句，并解释若选错形式会产生什么问题。',
    '重点核对 '+s.target+'；新句的主语、动词形式及句意应互相一致。');
  return [first,second];
}
function drawSessionOriginals(unitId, sid, level, grade, previousIds) {
  const corpus=KB.cpp_corpus, route=corpus.routes[unitId+'-'+sid] || {};
  const requested={L:5,M:6,H:8}[level];
  const weighted=Object.entries(route).map(([id,skill])=>{
    const item=corpus.items[id], passage=corpus.passages[item.group] || '';
    const words=(passage+' '+item.stem+' '+item.options.join(' ')).match(/[a-z]+/ig)?.length || 0;
    const load=item.grade*6 + Math.min(words,100)/4 + (item.options.length?0:5);
    const target=grade*6+{L:-1,M:6,H:16}[level];
    const score= -Math.abs(load-target) + (item.key?3:0)
      + Math.random()*8 - (previousIds.has(id)?16:0);
    return {item,skill,score};
  }).sort((a,b)=>Number(b.item.kind==='真题')-Number(a.item.kind==='真题') || b.score-a.score);
  const selected=[], seen=new Set();
  let passageId='', hasWriting=false;
  for(const {item,skill} of weighted){
    if(item.group && passageId && item.group!==passageId || item.qtype==='书面表达' && hasWriting)continue;
    const stem=item.stem.replace(/[\s'’.,!?＿_。？！]/g,'').toLowerCase();
    // Instruction-only stems must retain their options when identifying duplicates.
    const signature=stem.length>3 && !/不同类|不相同|发音不同/.test(stem) ? stem :
      stem+item.options.slice().sort().join('|').toLowerCase();
    if(seen.has(signature))continue;
    seen.add(signature);
    if(item.group)passageId=item.group;
    if(item.qtype==='书面表达')hasWriting=true;
    selected.push({item,skill});
    if(selected.length>=requested)break;
  }
  return selected;
}

function originalSections(selected, templates, session, level) {
  if(!selected.length)return templates;
  const groups=new Map();
  for(const {item,skill} of selected){
    const name=item.group?'原卷阅读':item.qtype==='书面表达'?'原卷写作':item.options.length?'原卷选择与辨析':'原卷书面运用';
    if(!groups.has(name))groups.set(name,{name,qs:[]});
    const group=groups.get(name);
    if(item.group)group.passage=KB.cpp_corpus.passages[item.group];
    const head=item.head.replace(/^[一二三四五六七八九十IVXivx\d]+[、.．]\s*/,'')
      .replace(/[（(](?:共\s*)?\d+\s*分[）)]/g,'').trim();
    const writing=item.qtype==='书面表达';
    const key=item.key || (writing?'按原卷题干列出的内容、格式和语言要求批阅。':'尚无可用答案，请教师对照原卷核定。');
    const task=exercise((head?head+'　':'')+item.stem,key,writing?6:item.options.length?1:2,item.options);
    const prefix=item.group?'rd.':skill.startsWith('课次词汇')?'vo.':'';
    const topics=session.topics.filter(id=>id.startsWith(prefix));
    Object.assign(task,{sourceItem:item,skill,topicIds:topics.length?topics:session.topics,open:writing,
      keyLabel:writing?'批阅要点':item.reviewed?'核对参考答案':item.key?'配套答案索引':'答案待核'});
    group.qs.push(task);
  }
  const sections=[...groups.values()];
  // Once the corpus supplies the complete assignment, print only the original items.
  // Listening, speaking and project sessions still require their textbook performance task.
  const completeSkill=session.category==='reading'?sections.some(part=>part.passage):
    session.category==='writing'?selected.some(({item})=>item.qtype==='书面表达'):['grammar','vocab','phonics'].includes(session.category);
  if(completeSkill && selected.length>={L:5,M:6,H:8}[level])return sections;
  const supplementary=['oracy','writing'].includes(session.category)?[...templates]:[...templates].reverse();
  while(sections.length<3 && supplementary.length){
    const part=supplementary.shift();
    if(part.name==='完成作品' && selected.some(({item})=>item.qtype==='书面表达'))continue;
    // Keep prompts referring to a preceding textbook task together.
    if(part.qs.some(q=>/第 1 题|上述情境/.test(q.stem)))continue;
    if(part.qs.some(q=>/从作品中选/.test(q.stem)) && !selected.some(({item})=>item.qtype==='书面表达'))continue;
    sections.push({...part,name:part.name+'（课次配套）'});
  }
  return sections;
}

function originalMarkup(value){
  return esc(value).replace(/&lt;u&gt;/gi,'<u>').replace(/&lt;\/u&gt;/gi,'</u>').replace(/\n/g,'<br>');
}

function makeSessionPaper(unitId,sid,level,previousIds=new Set()) {
  if (!Object.hasOwn(homeworkTiers,level)) throw Error('请选择一个难度');
  const [lv,un]=unitId.split('-'), unit=KB.cpp_sessions.levels[lv]?.[un];
  const s=unit?.sessions.find(s=>s.id===sid);
  if (!s) throw Error('没有找到这节课的目标');
  const items=KB.cpp_homework_items[unitId], card=CPP.units.find(u=>u.id===unitId), quant=unit.quantified;
  const num=Number(sid.slice(1)), tier=homeworkTiers[level];
  const low=level==='L', high=level==='H', sentences=tier.sentences;
  const pages=s.pages, cat=s.category;
  let instructions='', sections=[];
  const section=(name,...qs)=>sections.push({name,qs});
  const upper=Number(lv.slice(1))>=4;
  const answerEnglish=low?'可以用关键词、短语或图示作答。':high?'用英语写出结论，并说明依据。':'用一至两句英语回答。';
  const readBook=()=>{instructions='配学生书 '+pages+' 完成。'+([3,11].includes(num)?'读后题可翻回《'+s.text+'》'+s.textPages+' 查证。':'');};
  if(cat==='grammar'){
    const [first,second]=grammarSections(s,unitId,items,level);
    section(low?'选词填空':high?'语法改错':'语法填空',first);
    section('句型运用',second);
    section('情境表达',openTask('围绕“'+card.theme+'”，'+(low?'用本课句型说一句自己的话并写下来。':high?'写一段三句以上的小对话，在两处使用本课语法，再圈出关键形式。':'写一个两句小对话，至少一次用到本课句型。'),
      '情境贴合“'+card.theme+'”，正确运用 '+s.target+'。'+(high?'两处形式均能解释。':''),sentences+1));
  } else if(cat==='phonics'){
    const ph=items.phonics,[correct,...others]=ph.options;
    section('语音与拼写',low?pickExercise(ph.stem,correct,others):exercise(
      (high?'判断并解释。':'圈出正确项。')+ph.stem+'　'+shuffle(ph.options).join(' / '),correct+(high?'；说明哪个字母或组合符合规则。':''),high?2:1));
    const samples=(s.words||[]).filter(w=>/^[A-Za-z][A-Za-z -]+$/.test(w)).slice(0,5);
    if(!samples.length)readBook();
    section('规则运用',openTask('从'+(samples.length?'词组「'+samples.join('、')+'」':'学生书 '+pages+' 的示例')+'选'+(low?'一':'两')+'项，写下来并标出与本课规则有关的字母。'+(high?'比较两项的拼写或读音。':''),
      '按 '+s.target+' 核对；字母位置和读音应与所选示例相符。',2));
    section('迁移练习',openTask(num===5 && unitId==='G0-U1'?'写下自己名字的首字母及其小写形式，再写出另一个大小写字母对。':
      '为同桌设计一张“'+s.target+'”练习卡。'+(low?'写一个例词，圈出目标部分。':high?'给出两个容易混淆的例子，在背面写出判断方法和答案。':'写两个例词，标出目标部分，并给出一句读写提示。'),
      '示例符合本课规则，标注准确。'+(high?'须清楚说明两例的异同。':''),sentences+1));
  } else if(cat==='vocab' || (cat==='reading' && (num===2 || num===3))){
    const [first,second,third]=wordSections(s,unit,items,level);
    section(low?'词义选择':'词汇运用',first,second);
    const vocabularyGrade = upper && high
      ? openTask('选一个本课词，先写一句话让同学从上下文猜出词义，再说明哪条线索最有用。','句中有可推断的线索，与目标词义一致。',3)
      : null;
    section('用词表达',...[third,vocabularyGrade].filter(Boolean));
    if(cat==='reading'){
      readBook();
      section('课文理解',openTask('结合《'+s.text+'》：'+(s.think?.[0] || readingPrompt(s.strategy))+'　'+answerEnglish,
        '根据指定课文批阅；事实与原文一致，观点题接受有依据的不同回答。',sentences+1));
    } else if(num===1){
      section('话题表达',openTask(card.bigQuestionEn+'　'+(low?'选一个本课词，画或写出你的答案并标注英文。':high?'用本课词给出观点、理由和具体例子。':'用两个本课词回答，并补充一个细节。'),
        '回应单元大问题，用词准确；例子与回答相关。',sentences+1));
    } else{
      section('读前准备',openTask('读标题《'+s.text+'》。从今天的词里选'+(low?'一个':'两个')+'，'+(high?'写一个有依据的预测，并写出阅读时想验证的问题。':'猜想它可能和故事有什么关系。'),
        '本题是读前预测。目标词与预测之间有合理联系即可。',sentences+1));
    }
  } else if(cat==='reading'){
    readBook();
    const pre=num===8, end=num===10, review=num===11;
    section(pre?'读前观察':'提取信息',openTask('看学生书 '+pages+'《'+s.text+'》。'+(pre?'从本页标题、插图或活动中写出一条线索。':
      end?'找出这一部分新出现的一个变化，写出变化前后的情况。':review?'列出本篇课文两个关键内容，并按文中顺序排列。':'找出本课介绍的人物或事物，并记录一个具体细节。')+'　'+answerEnglish,
      '以指定页为准；所列信息可从该页或该课回顾的课文中定位。',sentences+1));
    section('阅读策略',openTask((pre?'只用本页的读前材料尝试“'+s.strategy+'”。记录你观察到的一点，并说出还需读正文验证什么。':readingPrompt(s.strategy))+(low?' 可以先圈画，再用关键词标注。':high?' 用两条不同的线索支持你的判断。':' 补上一处原文线索。'),
      '策略：'+s.strategy+'。接受符合课文的例子和合理解释。',sentences+1));
    section(pre?'预测与提问':review?'复述与评价':'理解与表达',openTask((pre?'用一个疑问句写出你读这篇课文时想弄清的事。':s.think?.[0] || '用自己的话说出本课最重要的一点。')+'　'+answerEnglish,
      pre?'问题与标题或读前线索有关，能够在阅读中验证。':'答案符合本页内容；评价和个人经验题言之有据即可。',sentences+1));
  } else if(cat==='writing'){
    const task=(quant.writing || card.writing.task).trim();
    const focus=(quant.writingFocus||card.writing.focus).split('\n')[0];
    section('写前准备',openTask('本课写作任务：'+task+'。先列出'+(high?'三项':'两项')+'准备使用的词、信息或字母。','所列材料支持本课指定的成品；拼写与语意正确。',2));
    section('完成作品',openTask('完成上述任务。重点检查「'+focus+'」。'+(low?'可参照学生书范例完成一个基本版本。':high?'独立完成，并在作品旁标注一处你有意采用的写作技巧。':'按本课格式独立完成，并使用本课写作要点。'),
      '围绕指定任务；体裁或书写形式符合要求；正确体现「'+focus+'」。',low?3:high?7:5));
    section('校对修改',openTask('从作品中选一处，'+(low?'圈出符合本课书写要求的部分。':'写下修改前后的版本，并说明改动理由。'),
      '能联系本课写作要点核对自己的作品。',2));
  } else {
    const task=cat==='oracy' ? s.focus.split(/听力[：:]/)[0].trim() : s.focus;
    if(cat==='oracy')instructions='听力部分请使用学生书 '+s.audioPages+' 配套音频《'+s.audioTitle+'》。其余部分可先做书面准备，再结对演练。';
    section(cat==='project'?'项目准备':'情境准备',openTask('本课任务：'+task+'。'+(low?'写出需要介绍的对象或一项行动。':high?'确定对象和目的，列出两个能让任务成功的具体条件。':'说明和谁交流、想达成什么结果。'),
      '答案须与本课任务对象和目的相符。',2));
    section(cat==='project'?'制作与展示':'对话运用',openTask(cat==='project'?
      '为该项目设计'+(low?'一张带英文标签的草图。':high?'一份可展示的方案，写出步骤、理由和预期结果。':'一张项目说明卡，写出做法和预期结果。'):
      '按上述情境写'+(low?'一组问答。':high?'三轮对话，加入一次追问或澄清，最后达成任务目标。':'两轮有来有回的对话。')+
      (s.words?.length?' 至少用到一个任务词，例如 '+s.words.slice(0,3).join('、')+'。':s.cue?' 可以参考提示语 '+s.cue:''),
      cat==='project'?'方案可实施；英语标签或说明与展示内容对应。':'对话双方回应相关，语言得体，能完成本节的交际任务。',low?3:high?7:5));
    section('完成与反馈',openTask(cat==='project'?'用英语向同学介绍作品。写下'+(high?'一个同学可能提出的问题及你的回答。':'你展示时会说的话。'):
      (low?'写出你会对同伴说的一句结束语或回应。':'同伴没有听清。写出你重新表达的说法，并说明它怎样帮助对方理解。'),
      '表达清楚且符合当前任务。'+(high?'追问、答复或改述应补充有效信息。':''),sentences+1));
  }
  if(cat==='oracy'){
    sections[0].name='听力与情境理解';
    sections[0].qs.unshift(openTask('听《'+s.audioTitle+'》，'+(low?'记录一个听到的关键词或短语。':high?'概括主要内容，记录两条来自录音的细节，并解释其中一条怎样支持你的概括。':'写出录音的主要话题，并记下一条支持它的细节。'),
      '对照学生书 '+s.audioPages+' 配套录音或教师用书录音稿核对。只给录音中有依据的信息计分。',sentences+1));
  }
  const target=s.target || s.strategy || s.focus.split('\n')[0];
  for(const part of sections){
    for(const q of part.qs){
      const mixedReading=cat==='reading' && (num===2 || num===3);
      const vocabulary=cat==='vocab' || (mixedReading && part.name!=='课文理解');
      q.skill ||= part.name+' · '+(vocabulary ? s.words.join('、') : target);
      q.topicIds=vocabulary ? card.vocab.topics :
        mixedReading ? s.topics.filter(id=>!card.vocab.topics.includes(id)) : s.topics;
    }
  }
  if(cat==='oracy')sections[0].qs[0].skill='听取信息 · '+s.audioTitle;
  const originals=drawSessionOriginals(unitId,sid,level,card.grade,previousIds);
  sections=originalSections(originals,sections,s,level);
  const qs=sections.flatMap(part=>part.qs);
  // A short homework paper uses 30 points; every printed point belongs to one task.
  qs.forEach((q,i)=>{q.points=Math.floor(30/qs.length)+(i<30%qs.length?1:0);q.sessionKey=unitId+'-'+sid;});
  return {unitId,sid,level,title:'CPP '+unitId+' · '+sid+' '+s.name+'作业卷',sections,instructions,
    originalCount:originals.length, realCount:originals.filter(({item})=>item.kind==='真题').length, minutes:tier.minutes,scope:s.focus,pages,total:30,topics:s.topics,category:cat};
}

function initHomework() {
  const unitSelect=$('#hwUnit'), sessionSelect=$('#hwSession'), result=$('#hwResult');
  const pref=store.get('cpp.sessionHomework.v1',{}) || {};
  let current=null, answerMode=false;
  unitSelect.innerHTML=CPP.levels.map(l=>'<optgroup label="'+esc(l.book)+'">'+CPP.units.filter(u=>u.level===l.id)
    .map(u=>'<option value="'+esc(u.id)+'">'+esc(u.id+'　'+u.theme)+'</option>').join('')+'</optgroup>').join('');
  if(CPP.units.some(u=>u.id===pref.unit))unitSelect.value=pref.unit;
  if(Object.hasOwn(homeworkTiers,pref.level))$('#hwTier input[value="'+pref.level+'"]').checked=true;
  function book(){const [lv,un]=unitSelect.value.split('-');return KB.cpp_sessions.levels[lv][un];}
  function tier(){return $('#hwTier input:checked').value;}
  function fillSessions(id){
    sessionSelect.innerHTML=book().sessions.map(s=>'<option value="'+s.id+'">'+esc(s.id+'　'+s.name)+'</option>').join('');
    if(book().sessions.some(s=>s.id===id))sessionSelect.value=id;
  }
  function refresh(){
    const s=book().sessions.find(s=>s.id===sessionSelect.value);
    const byGrade=new Map();
    (s.words||[]).forEach(w=>{
      const matches=book().wordGrades[w.toLowerCase().replaceAll('‐','-')];
      if(!matches)return;
      for(const g of matches){if(!byGrade.has(g))byGrade.set(g,[]);byGrade.get(g).push(w);}
    });
    const gradeRows=[...byGrade].sort(([a],[b])=>a-b).map(([g,words])=>'<li>'+esc(g<10?g+'年级':g===10?'高一':'高二')+' · '+esc(words.join('、'))+'</li>').join('');
    const quant=book().quantified, num=Number(s.id.slice(1));
    const reference=({4:quant.grammar,12:quant.grammar,5:quant.phonics,6:quant.writing,13:quant.listening})[num] || quant.theme;
    $('#hwScope').innerHTML='<summary>本课考查范围 · 学生书 '+esc(s.pages)+'</summary><p>'+esc(s.focus)+'</p>'+
      (reference?'<p>量化表 · 单元参照：'+esc(reference)+'</p>':'')+
      (gradeRows?'<p>本课词语在对标表中的年级</p><ul>'+gradeRows+'</ul>':'')+
      '<a href="'+esc(KB.cpp_sessions.source+'#u-'+unitSelect.value.toLowerCase()+'-k1-all')+'" target="_blank" rel="noopener">查看原始课次安排</a>';
    store.set('cpp.sessionHomework.v1',{unit:unitSelect.value,session:s.id,level:tier()});
    current=null;result.replaceChildren();
  }
  function render(){
    if(!current)return;
    let number=0;
    const body=current.sections.map((part,index)=>'<h3 class="sec">'+('一二三四'[index])+'、'+esc(part.name)+'</h3>'+(part.passage?'<div class="passage">'+originalMarkup(part.passage)+'</div>':'')+
      part.qs.map(q=>{
        const lines='<div class="hwLines">'+Array.from({length:q.lines},()=>'<div></div>').join('')+'</div>';
        return '<div class="q"><strong>'+ ++number +'.</strong> '+originalMarkup(q.stem)+' <span class="meta">（'+q.points+' 分）</span>'+
          (q.options.length?'<div class="hwOptions">'+q.options.map((v,i)=>originalMarkup((q.sourceItem?.group && /^[TF]（/.test(v)?'':String.fromCharCode(65+i)+'. ')+v)).join('　　')+'</div>':'')+
          (q.sourceItem?'<div class="meta hwSource">'+esc(q.sourceItem.kind)+'原卷 · '+(q.sourceItem.grade===7?'小升初':q.sourceItem.grade+'年级')+' · <a href="https://github.com/zhuguli1021-eng/primary-english-knowledge-graph/blob/main/corpus/'+q.sourceItem.file.split('/').map(encodeURIComponent).join('/')+'" target="_blank" rel="noopener">'+esc(q.sourceItem.source)+'</a>'+esc(q.sourceItem.no?' · '+(q.sourceItem.group?'篇内第 ':'第 ')+q.sourceItem.no+' 题':'')+'</div>':'')+
          (answerMode?'<p class="explain"><b>'+(q.keyLabel || (q.open?'批阅要点':'参考答案'))+'</b>　'+esc(q.key)+'</p>'+
           '<small class="meta">'+esc(q.sessionKey+' · '+q.skill+(q.bankId?' · 精编题 '+q.bankId:''))+'</small>':lines)+'</div>';
      }).join('')).join('');
    result.innerHTML='<div class="row noprint hwActions"><button class="btn" id="hwToggle">'+(answerMode?'查看学生卷':'查看教师答案')+'</button>'+
      (CAN_PRINT?'<button class="btn" id="hwPrint">打印当前卷</button>':'')+'</div><article class="card hwSheet"><h2>'+
      esc(current.title)+(answerMode?' · 教师答案':'')+'</h2><p>'+esc(homeworkTiers[current.level].name)+'　满分 '+current.total+
      ' 分　建议 '+current.minutes+' 分钟　姓名 __________</p>'+
      '<p class="hwCoverage">'+(current.originalCount?'本卷抽取 '+current.originalCount+' 道语料原题，其中 '+current.realCount+' 道来自标记为真题的试卷。':'本课暂无匹配的语料原题，以下为课次配套练习。')+'</p>'+
      (current.instructions?'<p>'+esc(current.instructions)+'</p>':'')+body+'</article>';
    $('#hwToggle').onclick=()=>{answerMode=!answerMode;render();};
    if($('#hwPrint'))$('#hwPrint').onclick=()=>window.print();
  }
  $('#hwGenerate').onclick=()=>{
    const previousIds=new Set(current?.sections.flatMap(part=>part.qs.map(q=>q.sourceItem?.id)) || []);
    current=makeSessionPaper(unitSelect.value,sessionSelect.value,tier(),previousIds);
    answerMode=false;
    if(current.originalCount){
      render();
    } else {
      const available=book().sessions.filter(s=>KB.cpp_corpus.routes[current.unitId+'-'+s.id]).map(s=>s.id);
      result.innerHTML='<div class="card"><p><b>'+esc(current.unitId+' '+current.sid)+' 暂无匹配的语料原题。</b></p>'+
        (available.length?'<p class="muted">本单元可抽到原题的课次：'+available.join('、')+'。</p>':'')+
        '<button class="btn" id="hwLessonOnly">查看本课配套练习</button></div>';
      $('#hwLessonOnly').onclick=render;
    }
    $('#hwResult').scrollIntoView({block:'start',behavior:'smooth'});
  };
  unitSelect.onchange=()=>{fillSessions(sessionSelect.value);refresh();};
  sessionSelect.onchange=refresh;
  $('#hwTier').onchange=refresh;
  $('#hwMode').onclick=()=>{
    const advanced=$('#hwAdvanced').hidden;
    $('#hwAdvanced').hidden=!advanced;$('#hwQuick').hidden=advanced;
    $('#hwMode').textContent=advanced?'返回按课次一键组卷':'高级组卷';
  };
  fillSessions(pref.session);refresh();
}
initHomework();
