/* One document model drives A4 PDF, editable Word, and the teacher answer preview. */
const HomeworkExport=(()=>{
  const utf=new TextEncoder();
  function lines(bank,p,answers){
    const out=[];
    const add=(text,style='normal')=>out.push({text:String(text),style});
    add(answers?'教师参考答案':Homework.title(p),'title');
    add(answers?Homework.title(p):'姓名：____________　班级：____________　日期：____________','subtitle');
    for(const [i,s] of p.sections.entries()){
      if(!s.ids.length)continue;
      add('一二三四五'[i]+'、'+Homework.names[s.block],'heading');
      for(const [j,id] of s.ids.entries()){
        const q=bank.items[id];
        if(answers){
          const answer=item=>{
            const n=item.options.indexOf(item.key);
            return (n<0?'':String.fromCharCode(65+n)+'. ')+item.key;
          };
          const key=q.parts?q.parts.map((part,k)=>'（'+(k+1)+'）'+answer(part)+(part.explain?'　'+part.explain:'')).join('　'):answer(q);
          add((j+1)+'. '+key+(q.explain?'　'+q.explain:''));
          continue;
        }
        add((j+1)+'. '+q.head,'prompt');
        if(q.stem)add(q.stem);
        if(q.options.length)add(q.options.map((v,n)=>String.fromCharCode(65+n)+'. '+v).join('　　'));
        for(const [k,part] of (q.parts||[]).entries()){
          add('（'+(k+1)+'）'+part.stem+(part.stem.includes('_')?'':'　________'));
          if(part.options.length)add(part.options.map((v,n)=>String.fromCharCode(65+n)+'. '+v).join('　　'));
        }
        add('________________________________','space');
      }
    }
    return out;
  }
  const xml=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  function spans(text){
    let underline=false;const runs=[];
    for(const s of text.split(/(<\/?u>)/ig)){
      if(s.toLowerCase()==='<u>')underline=true;
      else if(s.toLowerCase()==='</u>')underline=false;
      else if(s)runs.push({s,underline});
    }
    return runs;
  }
  const crcTable=Array.from({length:256},(_,n)=>{
    for(let i=0;i<8;i++)n=(n&1)?0xedb88320^(n>>>1):n>>>1;return n>>>0;
  });
  function zip(files){
    const parts=[],central=[];let offset=0;
    function header(size,fields){
      const bytes=new Uint8Array(size),view=new DataView(bytes.buffer);
      for(const [at,n,v] of fields)view[n===2?'setUint16':'setUint32'](at,v,true);
      return bytes;
    }
    for(const [name,data] of files){
      const path=utf.encode(name);let crc=0xffffffff;
      for(const v of data)crc=crcTable[(crc^v)&255]^(crc>>>8);
      crc=(crc^0xffffffff)>>>0;
      const local=header(30,[[0,4,0x04034b50],[4,2,20],[6,2,2048],[12,2,33],[14,4,crc],[18,4,data.length],[22,4,data.length],[26,2,path.length]]);
      parts.push(local,path,data);
      central.push(header(46,[[0,4,0x02014b50],[4,2,20],[6,2,20],[8,2,2048],[14,2,33],[16,4,crc],[20,4,data.length],[24,4,data.length],[28,2,path.length],[42,4,offset]]),path);
      offset+=local.length+path.length+data.length;
    }
    const size=central.reduce((n,b)=>n+b.length,0);
    return new Blob([...parts,...central,header(22,[[0,4,0x06054b50],[8,2,files.length],[10,2,files.length],[12,4,size],[16,4,offset]])]);
  }
  function docx(bank,p){
    function paragraph(line){
      const {style,text}=line;
      const large=style==='title',bold=large||style==='heading', size=large?34:bold?27:23;
      const content=spans(text).map(({s,underline})=>'<w:r><w:rPr><w:rFonts w:ascii="Arial" w:eastAsia="宋体"/><w:sz w:val="'+size+'"/>'+(bold?'<w:b/>':'')+(underline?'<w:u w:val="single"/>':'')+'</w:rPr>'+
        s.split('\n').map(v=>'<w:t xml:space="preserve">'+xml(v)+'</w:t>').join('<w:br/>')+'</w:r>').join('');
      return '<w:p><w:pPr>'+(bold||style==='prompt'?'<w:keepNext/>':'')+(large?'<w:jc w:val="center"/>':'')+'<w:spacing w:after="90" w:line="300" w:lineRule="auto"/></w:pPr>'+content+'</w:p>';
    }
    const ns='http://schemas.openxmlformats.org/';
    const document='<w:document xmlns:w="'+ns+'wordprocessingml/2006/main"><w:body>'+lines(bank,p,false).map(paragraph).join('')+
      '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'+lines(bank,p,true).map(paragraph).join('')+
      '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1000" w:left="1100" w:right="1100" w:bottom="1000" w:header="500" w:footer="500" w:gutter="0"/></w:sectPr></w:body></w:document>';
    return zip([
      ['[Content_Types].xml',utf.encode('<Types xmlns="'+ns+'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')],
      ['_rels/.rels',utf.encode('<Relationships xmlns="'+ns+'package/2006/relationships"><Relationship Id="rId1" Type="'+ns+'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')],
      ['word/document.xml',utf.encode(document)]
    ]);
  }
  async function pdf(bank,p){
    // Rasterize with the device's installed Chinese font, including underline runs.
    const pages=[],width=595.28,height=841.89,margin=49,scale=3;
    const canvas=document.createElement('canvas');canvas.width=Math.ceil(width*scale);canvas.height=Math.ceil(height*scale);
    const ctx=canvas.getContext('2d');let y;
    function start(){ctx.setTransform(scale,0,0,scale,0,0);ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);ctx.fillStyle='#111';y=margin+14;}
    async function finish(){
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',0.92));
      if(!blob)throw Error('浏览器未能写入 PDF 页面');
      pages.push(new Uint8Array(await blob.arrayBuffer()));
    }
    for(const answers of [false,true]){
      start();
      for(const line of lines(bank,p,answers)){
        const size=line.style==='title'?18:line.style==='heading'?14:11.5;
        ctx.font=(line.style==='title'||line.style==='heading'?'bold ':'')+size+'px Arial,"PingFang SC","Microsoft YaHei",sans-serif';
        if((line.style==='heading'||line.style==='prompt')&&y>height-margin-55){await finish();start();}
        let x=margin;
        for(const {s,underline} of spans(line.text)){
          for(const token of s.match(/\n|[A-Za-z0-9_’'-]+|[^\n]/gu)||[]){
            if(token==='\n'){x=margin;y+=size*1.55;continue;}
            const w=ctx.measureText(token).width;
            if(x>margin && x+w>width-margin){x=margin;y+=size*1.55;}
            if(y>height-margin){await finish();start();x=margin;}
            ctx.fillText(token,x,y);
            if(underline)ctx.fillRect(x,y+1,w,0.7);
            x+=w;
          }
        }
        y+=size*1.6+(line.style==='space'?6:3);
      }
      await finish();
    }
    const chunks=[],offsets=[0];let total=0;
    function write(v){const a=typeof v==='string'?utf.encode(v):v;chunks.push(a);total+=a.length;}
    function object(n,body){offsets[n]=total;write(n+' 0 obj\n');for(const v of body)write(v);write('\nendobj\n');}
    write('%PDF-1.4\n');
    object(1,['<< /Type /Catalog /Pages 2 0 R >>']);
    object(2,['<< /Type /Pages /Count '+pages.length+' /Kids ['+pages.map((_,i)=>(3+3*i)+' 0 R').join(' ')+'] >>']);
    pages.forEach((bytes,i)=>{
      const n=3+i*3,cmd='q '+width+' 0 0 '+height+' 0 0 cm /P Do Q\n';
      object(n,['<< /Type /Page /Parent 2 0 R /MediaBox [0 0 '+width+' '+height+'] /Resources << /XObject << /P '+(n+2)+' 0 R >> >> /Contents '+(n+1)+' 0 R >>']);
      object(n+1,['<< /Length '+cmd.length+' >>\nstream\n',cmd,'endstream']);
      object(n+2,['<< /Type /XObject /Subtype /Image /Width '+canvas.width+' /Height '+canvas.height+' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length '+bytes.length+' >>\nstream\n',bytes,'\nendstream']);
    });
    const startXref=total;
    write('xref\n0 '+offsets.length+'\n0000000000 65535 f \n'+offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('')+
      'trailer\n<< /Size '+offsets.length+' /Root 1 0 R >>\nstartxref\n'+startXref+'\n%%EOF');
    return new Blob(chunks,{type:'application/pdf'});
  }
  async function download(bank,papers,format,batch){
    const files=[];
    for(const p of papers.filter(p=>p.sections.some(s=>s.ids.length))){
      const blob=format==='pdf'?await pdf(bank,p):docx(bank,p);
      files.push([Homework.title(p).replaceAll('/','-')+'.'+format,new Uint8Array(await blob.arrayBuffer())]);
    }
    if(!files.length)return;
    const blob=batch?zip(files):new Blob([files[0][1]],{type:format==='pdf'?'application/pdf':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=batch?papers[0].unit+'-分层作业-'+format+'.zip':files[0][0];
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  }
  return {lines,docx,pdf,download};
})();
