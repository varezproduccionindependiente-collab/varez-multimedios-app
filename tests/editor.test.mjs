import test from 'node:test';
import assert from 'node:assert/strict';
import {JOB_VERSION,normalizeSelection,alignQuotes,planFromWordIds,prepareCandidates,saveJob,loadJob} from '../editor.mjs';

const text='La cultura nos salva. Trabajamos cada día para que todos puedan participar. Ese es nuestro compromiso. Ahora empieza otra pregunta';
const words=text.split(' ').map((word,i)=>({word,start:i*.4+.1,end:i*.4+.44}));
const context=100, c={title:'La cultura nos salva',start:100,end:106.9,opening_words:'La cultura nos salva',closing_words:'Ese es nuestro compromiso',hook_closing_words:'La cultura nos salva',hook_end:102};

test('fewer than five is valid, zero is valid; no manufactured or duplicate windows',()=>{
  assert.equal(normalizeSelection([c,{...c,title:'Duplicado'},{start:'mal',end:25}],200).length,1);
  assert.deepEqual(normalizeSelection([],200),[]);
  assert.equal(normalizeSelection([{...c,end:180}],200)[0].end,180);
});
test('clip 4: absent, relative or whole-clip hook timestamp recovers from real words',()=>{
  for(const hook_end of [undefined,null,NaN,1.8,c.end,999]){
    const p=alignQuotes({...c,hook_end},words,context,200);
    assert.ok(p,`failed hook ${hook_end}`);
    assert.ok(p.intro_end_rel>.7&&p.intro_end_rel<p.end-p.start-.7);
    assert.equal(p.words[0].word,'La');
    assert.equal(p.words.at(-1).word,'compromiso.');
    assert.ok(p.end<context+words[17].start,'must not include Ahora');
  }
});
test('tight gap after closing phrase does not add the next word',()=>{
  const w=structuredClone(words);w[17].start=w[16].end+.02;
  const p=alignQuotes(c,w,context,200);
  assert.ok(p.end<context+w[17].start);
});
test('word ID repair validates bounds and meaningful room for development',()=>{
  const answer={usable:true,first_word:0,last_word:16,hook_last_word:3,complete_start:true,complete_end:true,protagonist_hook:true};
  assert.ok(planFromWordIds(c,words,context,200,answer));
  for(const invalid of [{hook_last_word:16},{last_word:999},{first_word:-1},{first_word:0.5},{protagonist_hook:false},{usable:false}]){
    assert.equal(planFromWordIds(c,words,context,200,{...answer,...invalid}),null);
  }
});
test('an unmatchable quote requires review rather than an arbitrary fixed intro',()=>{
  assert.equal(alignQuotes({...c,hook_closing_words:'palabras que nadie dijo'},words,context,200),null);
});
test('clip 4 failure preserves clips 1–3, continues 5, reloads and retries only 4',async()=>{
  const memory=new Map(),storage={setItem:(k,v)=>memory.set(k,v),getItem:k=>memory.get(k)};
  let job={version:JOB_VERSION,id:'0123456789abcdef',clips:Array.from({length:5},(_,i)=>({...c,title:`Clip ${i+1}`})),entries:[]};
  const calls=[];
  const good=await prepareCandidates(job,async(clip,i)=>{calls.push(i);if(i===3)throw Error('network interrupted');return {...clip,source_index:i+1,source_paths:[`source-${i+1}`]}},()=>saveJob(storage,'job',job));
  assert.deepEqual(calls,[0,1,2,3,4]);assert.equal(good.length,4);
  job=loadJob(storage,'job');assert.equal(job.entries[0].clip.source_paths[0],'source-1');
  const retried=[];
  const complete=await prepareCandidates(job,async(clip,i)=>{retried.push(i);return {...clip,source_index:i+1}},()=>saveJob(storage,'job',job));
  assert.deepEqual(retried,[3]);assert.equal(complete.length,5);
});
test('editorial rejection yields four good clips and is not retried forever',async()=>{
  const j={clips:Array.from({length:5},()=>c),entries:[]};
  const good=await prepareCandidates(j,async(clip,i)=>i===3?null:clip);
  assert.equal(good.length,4);assert.equal(j.entries[3].status,'skipped');
  await prepareCandidates(j,()=>assert.fail('completed or rejected candidates must be reused'));
});
