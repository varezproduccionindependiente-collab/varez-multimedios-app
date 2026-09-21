import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import * as editorial from '../editor.mjs';

// Exercise the actual app entrypoint. Only external services/media extraction are fixtures.
async function runScenario(count,rejectFourth=false,interruptFourth=false,batchFast=false){
  const nodes=new Map();
  function element(){return {style:{},dataset:{},value:'',textContent:'',hidden:true,children:[],classList:{add(){},remove(){},toggle(){},contains(){return true}},addEventListener(){},appendChild(el){this.children.push(el)}}}
  const document={querySelector(selector){if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)},querySelectorAll(){return []},createElement:element};
  const memory=new Map([['varez_gemini_key','fixture'],['varez_groq_key','fixture'],['varez_github_pat','fixture']]);
  const storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)};
  const opening='La cultura nos salva porque construye una comunidad con memoria'.split(' '),middle=Array.from({length:65},(_,i)=>`desarrollo${i}`),hook='Sin cultura nuestra comunidad pierde su memoria su voz y también todo su futuro'.split(' '),closing='Por eso sostener estos espacios es nuestro compromiso con toda la comunidad'.split(' '),core=[...opening,...middle,...hook,...closing],tokens=[...core,'Ahora','empieza','otra','pregunta'];
  const words=tokens.map((word,i)=>({word,start:i*.45+4.1,end:i*.45+4.44})),last=core.length-1,hookFirst=opening.length+middle.length,hookLast=hookFirst+hook.length-1,quote=(from,to)=>words.slice(from,to+1).map(w=>w.word).join(' '),clipLength=words[last].end-4,rangeDuration=clipLength+8;
  const batchWords=Array.from({length:count},(_,clipIndex)=>words.map(word=>({...word,start:word.start+clipIndex*(rangeDuration+.8),end:word.end+clipIndex*(rangeDuration+.8)}))).flat();
  const clips=Array.from({length:count},(_,i)=>{const start=5+i*70,contextStart=start-4;return{title:`Clip ${i+1}`,start,end:start+clipLength,hook_start:contextStart+words[hookFirst].start,hook_end:contextStart+words[hookLast].end,hook_opening_words:quote(hookFirst,hookFirst+5),hook_closing_words:i===3&&rejectFourth?'cita ausente':quote(hookLast-5,hookLast),opening_words:quote(0,7),closing_words:quote(last-7,last),question_start:-1,question_end:-1,context_start_complete:true,context_end_complete:true,hook_context_complete:true,single_contiguous_hook:true,reason:'Idea completa',boundary_check:'Inicio y cierre completos'}});
  let manifests=[],outputs=[],dispatches=0,repairs=0,transcriptions=0;
  const json=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
  const fetch=async(url,options={})=>{
    if(url.includes('/upload/v1beta/files'))return new Response('{}',{headers:{'x-goog-upload-url':'https://fixture.invalid/upload'}});
    if(url==='https://fixture.invalid/upload')return json({file:{name:'files/fixture',uri:'https://fixture.invalid/video',mimeType:'video/mp4',state:'ACTIVE'}});
    if(options.method==='DELETE')return new Response(null,{status:204});
    if(url.includes(':generateContent')){
      const body=JSON.parse(options.body),repair=body.contents[0].parts[0].text.startsWith('Editá');
      if(repair)repairs++;
      return json({candidates:[{content:{parts:[{text:JSON.stringify(repair?{usable:false}:{clips})}]}}]});
    }
    if(url.includes('api.groq.com')){transcriptions++;if(interruptFourth&&transcriptions===4)return new Response('fixture failure',{status:401});return json({words:batchFast?batchWords:words})}
    if(url.includes('/releases?'))return json([{id:7,tag_name:'varez-worker-storage'}]);
    if(url.includes('/dispatches')){
      dispatches++;
      outputs.push(...manifests.at(-1).clips.map(c=>({name:c.output_path.split('/').at(-1),path:c.output_path,url:'https://fixture.invalid/'+c.source_index+'.mp4'})));
      return new Response(null,{status:204});
    }
    if(url.includes('?action=')){
      const action=new URL(url).searchParams.get('action'),body=JSON.parse(options.body||'{}');
      if(action==='upload-url'){const path=`jobs/${body.id}/${body.folder}/${body.name}`;return json({path,token:'fixture',signed_url:'https://fixture.invalid/upload'})}
      if(action==='download-url')return json({url:'https://fixture.invalid/download'});
      if(action==='output-status')return json({results:outputs});
    }
    assert.fail('Unexpected request: '+url);
  };
  const environment={...editorial,document,localStorage:storage,crypto:webcrypto,Blob,File,FormData,Response,AbortController,URL,setTimeout,clearTimeout,setInterval,clearInterval,fetch,console,alert:msg=>assert.fail(msg),createClient:()=>({storage:{from:()=>({uploadToSignedUrl:async(path,token,blob)=>{if(path.endsWith('.json'))manifests.push(JSON.parse(await blob.text()));return {error:null}}})}})};
  let context=vm.createContext(environment);
  const code=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
  vm.runInContext(code,context);
  vm.runInContext("getFF=async()=>({exec:async()=>0,read:async()=>new Uint8Array([1,2,3]),del:async()=>{}});S.file=new File(['fixture video'],'interview.mp4',{type:'video/mp4'});S.dur=400;",context);
  await vm.runInContext('runJob()',context);
  const result=JSON.parse(JSON.stringify(vm.runInContext('S.job',context)));
  assert.equal(result.phase,'done');assert.equal(result.outputPaths.length,count-(rejectFourth||interruptFourth?1:0));
  assert.equal(dispatches,count?1:0);assert.equal(transcriptions,batchFast&&count?1:count);
  if(rejectFourth){assert.equal(result.entries[3].status,'skipped');assert.ok(result.outputPaths.some(p=>p.endsWith('output-05.mp4')));assert.equal(repairs,1)}
  if(interruptFourth){
    assert.equal(result.entries[3].status,'error');
    context=vm.createContext({...environment});
    vm.runInContext(code,context);
    // Reload first, then reselect the original file. The old job ID and completed clips survive.
    vm.runInContext("getFF=async()=>({exec:async()=>0,read:async()=>new Uint8Array([1,2,3]),del:async()=>{}});S.file=new File(['fixture video'],'interview.mp4',{type:'video/mp4'});S.dur=400;",context);
    await vm.runInContext('runJob()',context);
    assert.equal(dispatches,2);
    assert.equal(transcriptions,6,'only the failed fourth clip is transcribed again');
    assert.deepEqual(manifests[1].clips.map(c=>c.source_index),[4]);
    assert.equal(vm.runInContext('S.job.outputPaths.length',context),5);
    assert.equal(vm.runInContext('S.job.id',context),result.id);
  }else{
    await vm.runInContext('runJob()',context);
    assert.equal(dispatches,count?1:0,'reopening results must not repeat render');
    assert.equal(transcriptions,batchFast&&count?1:count,'reopening results must reuse transcripts');
  }
  assert.equal(JSON.parse(memory.get('varez_multimedios_job_v33')).phase,'done');
  assert.match(nodes.get('#elapsed').textContent,/^\d{2}:\d{2}(?::\d{2})?$/);
  return result;
}
test('actual app delivers two clips with two outputs; does not wait for five',()=>runScenario(2));
test('actual app reviews rejected fourth clip and delivers 1, 2, 3, 5',()=>runScenario(5,true));
test('actual app reload restores the job and retries only failed clip 4',()=>runScenario(5,false,true));
test('actual app transcribes five selected ranges in one batch',()=>runScenario(5,false,false,true));
test('no usable material finishes without dispatching a render',()=>runScenario(0));
