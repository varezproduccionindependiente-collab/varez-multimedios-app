import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const OWNER='varezproduccionindependiente-collab', REPO='varez-multimedios-app', WORKFLOW='render-multimedios.yml';
const CLOUD='https://fggygohsaoxlscgefshm.supabase.co/functions/v1/varez-cloud', BUCKET='varez-multimedios-cloud';
const SB=createClient('https://fggygohsaoxlscgefshm.supabase.co','sb_publishable_doSKfwIooDNd-6A3FAXyAg_7Otf8VCF');
const S={file:null,dur:0,mode:'auto',category:'Entrevista',settings:{captions:true,qa:true,reframe:true},ff:null,mounted:false,jobId:null,release:null,clips:[]};
const LS={pin:'varez_multimedios_pin',gemini:'varez_gemini_key',groq:'varez_groq_key',github:'varez_github_pat',release:'varez_worker_release'};
function esc(s=''){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function fmt(sec){sec=Math.max(0,Number(sec)||0);return Math.floor(sec/60)+':'+String(Math.floor(sec%60)).padStart(2,'0')}
function progress(p,l,d=''){p=Math.max(0,Math.min(100,Math.round(p)));$('#progress').style.display='block';$('#ppct').textContent=p+'%';$('#pbar').style.width=p+'%';$('#plabel').textContent=l;$('#log').textContent=d;$('#log').className='log'}
function fail(msg){$('#log').textContent=msg;$('#log').className='log error';throw new Error(msg)}
function cfg(){return{gemini:localStorage.getItem(LS.gemini)||'',groq:localStorage.getItem(LS.groq)||'',github:localStorage.getItem(LS.github)||''}}
function ensureLogin(){if(localStorage.getItem(LS.pin)!=='053362')$('#loginModal').classList.add('show')}
function ensureConfig(){const c=cfg();if(!c.gemini||!c.groq||!c.github){openSettings();return false}return true}
async function cloud(action,opt={}){const headers={'x-varez-pin':localStorage.getItem(LS.pin)||'',...(opt.headers||{})};const r=await fetch(CLOUD+'?action='+encodeURIComponent(action),{...opt,headers});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.error||('Cloud '+r.status));return d}
async function cloudUpload(name,blob,type='application/octet-stream',folder='source'){const s=await cloud('upload-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:S.jobId,name,folder})});const {error}=await SB.storage.from(BUCKET).uploadToSignedUrl(s.path,s.token,blob,{contentType:type});if(error)throw new Error('Supabase upload: '+error.message);const dl=await cloud('download-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:s.path})});return{path:s.path,url:dl.url}}
async function cloudUploadSpec(name,folder='output'){return cloud('upload-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:S.jobId,name,folder})})}

function openSettings(){const c=cfg();$('#geminiKey').value=c.gemini;$('#groqKey').value=c.groq;$('#githubToken').value=c.github;$('#settingsModal').classList.add('show')}
$('#settingsBtn').onclick=openSettings;$('#cancelSettings').onclick=()=>$('#settingsModal').classList.remove('show');
$('#saveSettings').onclick=()=>{const g=$('#geminiKey').value.trim(),q=$('#groqKey').value.trim(),h=$('#githubToken').value.trim();if(!g||!q||!h){$('#settingsMsg').textContent='Completá las tres claves.';$('#settingsMsg').className='help error';return}localStorage.setItem(LS.gemini,g);localStorage.setItem(LS.groq,q);localStorage.setItem(LS.github,h);$('#settingsMsg').textContent='Guardado en este iPhone.';$('#settingsMsg').className='help ok';setTimeout(()=>$('#settingsModal').classList.remove('show'),450)};
$('#login').onclick=()=>{const v=$('#pin').value.trim();if(v!=='053362'){localStorage.removeItem(LS.pin);$('#loginErr').textContent='Clave incorrecta.';return}localStorage.setItem(LS.pin,v);$('#loginModal').classList.remove('show');if(!ensureConfig())openSettings()};

$('#choose').onclick=e=>{e.preventDefault();$('#file').click()};$('#file').onchange=()=>pick($('#file').files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(x=>drop.addEventListener(x,e=>{e.preventDefault()}));drop.addEventListener('drop',e=>{e.preventDefault();pick(e.dataTransfer.files[0])});
function pick(f){if(!f)return;if(f.size>2147483648)return alert('Por ahora el video para Gemini debe pesar menos de 2 GB.');S.file=f;S.ff=null;S.mounted=false;const v=$('#preview');if(v.src)URL.revokeObjectURL(v.src);v.src=URL.createObjectURL(f);v.onloadedmetadata=()=>{S.dur=v.duration||0;if(S.dur>1800)alert('La beta admite notas de hasta 30 minutos.');$('#meta').style.display='block';$('#meta').innerHTML='<b>'+esc(f.name)+'</b><span>'+(f.size/1024/1024).toFixed(1)+' MB · '+fmt(S.dur)+'</span>'}}
$$('[data-mode]').forEach(b=>b.onclick=()=>{$$('[data-mode]').forEach(x=>x.classList.remove('active'));b.classList.add('active');S.mode=b.dataset.mode;$('#request').style.display=S.mode==='specific'?'block':'none'});
$$('.chip').forEach(b=>b.onclick=()=>{$$('.chip').forEach(x=>x.classList.remove('active'));b.classList.add('active');S.category=b.textContent.trim()});
$$('[data-setting]').forEach(t=>t.onclick=()=>{t.classList.toggle('on');S.settings[t.dataset.setting]=t.classList.contains('on')});

async function gh(url,opt={}){const t=cfg().github;const headers={Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10',Authorization:'Bearer '+t,...(opt.headers||{})};const r=await fetch(url,{...opt,headers});if(!r.ok){const x=await r.text();throw new Error('GitHub: '+r.status+' '+x.slice(0,350))}if(r.status===204)return null;return r.json()}
async function ensureRelease(){if(S.release)return S.release;progress(4,'Preparando editor remoto…','Conectando con GitHub.');const list=await gh(`https://api.github.com/repos/${OWNER}/${REPO}/releases?per_page=100`);let rel=list.find(x=>x.tag_name==='varez-worker-storage');if(!rel){rel=await gh(`https://api.github.com/repos/${OWNER}/${REPO}/releases`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tag_name:'varez-worker-storage',target_commitish:'main',name:'Varez Worker Storage',body:'Almacenamiento temporal privado para Varez Multimedios.',draft:true,prerelease:false})})}S.release=rel;localStorage.setItem(LS.release,String(rel.id));return rel}
async function listAssets(){const rel=await ensureRelease();return gh(`https://api.github.com/repos/${OWNER}/${REPO}/releases/${rel.id}/assets?per_page=100`)}
async function deleteAsset(asset){await gh(`https://api.github.com/repos/${OWNER}/${REPO}/releases/assets/${asset.id}`,{method:'DELETE'})}
async function uploadAsset(name,blob,type='application/octet-stream'){const rel=await ensureRelease();const existing=(await listAssets()).filter(x=>x.name===name);for(const x of existing)await deleteAsset(x);const url=`https://uploads.github.com/repos/${OWNER}/${REPO}/releases/${rel.id}/assets?name=${encodeURIComponent(name)}`;const r=await fetch(url,{method:'POST',headers:{Authorization:'Bearer '+cfg().github,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2026-03-10','Content-Type':type},body:blob});if(!r.ok)throw new Error('No pude subir '+name+' a GitHub: '+r.status+' '+(await r.text()).slice(0,300));return r.json()}
async function dispatch(manifestUrl){const rel=await ensureRelease();await gh(`https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ref:'main',inputs:{release_id:String(rel.id),job_id:S.jobId,manifest_url:manifestUrl}})})}

async function geminiUpload(file){const key=cfg().gemini,mime=file.type||'video/mp4';progress(8,'Subiendo video a Gemini…','El video se usa solo para elegir los cinco mejores momentos.');const start=await fetch('https://generativelanguage.googleapis.com/upload/v1beta/files',{method:'POST',headers:{'x-goog-api-key':key,'X-Goog-Upload-Protocol':'resumable','X-Goog-Upload-Command':'start','X-Goog-Upload-Header-Content-Length':String(file.size),'X-Goog-Upload-Header-Content-Type':mime,'Content-Type':'application/json'},body:JSON.stringify({file:{display_name:file.name}})});if(!start.ok)throw new Error('Gemini upload: '+start.status+' '+(await start.text()).slice(0,300));const uploadUrl=start.headers.get('x-goog-upload-url');if(!uploadUrl)throw new Error('Gemini no devolvió la URL de carga.');const up=await fetch(uploadUrl,{method:'POST',headers:{'X-Goog-Upload-Offset':'0','X-Goog-Upload-Command':'upload, finalize','Content-Type':mime},body:file});if(!up.ok)throw new Error('Gemini upload: '+up.status+' '+(await up.text()).slice(0,300));let info=await up.json();for(let i=0;i<120&&info.file?.state==='PROCESSING';i++){progress(12,'Gemini está procesando el video…','Puede tardar unos minutos según el tamaño.');await new Promise(r=>setTimeout(r,3000));const g=await fetch('https://generativelanguage.googleapis.com/v1beta/'+info.file.name,{headers:{'x-goog-api-key':key}});if(!g.ok)throw new Error('Gemini file status: '+g.status);info={file:await g.json()}}if(info.file?.state&&info.file.state!=='ACTIVE')throw new Error('Gemini no pudo preparar el video. Estado: '+info.file.state);return info.file}
async function geminiSelect(fileInfo){
  progress(20,'Gemini está mirando la nota completa…','Buscando cinco momentos que realmente funcionen como reels.');
  const total=Math.max(1,Number(S.dur)||1);
  const short=total<150, medium=total>=150&&total<300;
  const minDur=short?14:medium?18:25;
  const maxDur=short?30:medium?45:58;
  const overlapRule=short
    ?'Como el video es corto, los cinco clips PUEDEN superponerse parcialmente si hace falta, pero cada uno debe tener un foco o idea distinta.'
    :medium
      ?'Evitá superposiciones grandes; una superposición breve es aceptable si permite conservar una respuesta completa.'
      :'No superpongas los cinco clips.';
  const pol=S.category.toLowerCase().includes('pol')
    ?'Para contenido político, seleccioná por claridad, relevancia periodística, autosuficiencia y valor informativo. No favorezcas ni perjudiques partidos, candidatos o funcionarios; no hagas rankings ni recomendaciones electorales.'
    :'';
  const editorialRules=`Tu criterio debe ser el de un editor humano exigente, no el de un buscador de frases sueltas.
Cada clip tiene que contar una mini historia completa: planteo o contexto suficiente, desarrollo y remate/cierre. Debe entenderse sin haber visto la entrevista completa.
INICIO: empezá antes de la primera palabra de una oración o pregunta completa. Nunca arranques a mitad de palabra, a mitad de oración, ni con una respuesta huérfana como "sí", "no", "también", "porque", "entonces", "pero", "él", "ella", "eso" o "esto" si el referente no se entiende. Conservá una respiración breve antes de la primera palabra.
FINAL: terminá después de la última palabra que cierra la idea y antes de que comience una idea nueva. Nunca cierres en conectores o promesas de continuación como "y", "pero", "porque", "entonces", "además", "por eso", "yo creo que", "lo que pasa es". No incluyas las primeras palabras del tema siguiente. Dejá solamente entre 0.25 y 0.65 segundos de aire luego del cierre; no agregues segundos de relleno.
GANCHO INICIAL OBLIGATORIO: elegí un comienzo con una afirmación contundente, completa y autosuficiente del protagonista. NO uses la pregunta del entrevistador como gancho. La frase inicial del protagonista irá en blanco y negro y audio telefónico; después continúa su desarrollo en color y audio normal, sin cambiar el orden ni el sentido. Si la respuesta necesita una pregunta para entenderse, elegí otro comienzo autosuficiente. Devolvé hook_end como el segundo absoluto donde termina esa frase contundente completa (no un número fijo de segundos) y hook_closing_words como sus últimas 5 a 12 palabras textuales. Tiene que quedar desarrollo después del gancho. Para estos clips question_start y question_end son -1.
SELECCIÓN: preferí una idea completa de 28 segundos antes que una idea más llamativa cortada o inflada a 45. La duración es un rango, no una obligación de rellenar. Rechazá todo fragmento que requiera contexto exterior o que no tenga cierre natural.
PRECISIÓN: opening_words debe copiar literalmente las primeras 5 a 12 palabras habladas del clip y closing_words las últimas 5 a 12. Esas citas se usarán para ajustar el corte con la transcripción.`;
  const prompt=`Sos el editor senior de Varez Servicios para Multimedios. Mirá y escuchá el video completo, que dura ${total.toFixed(1)} segundos. Elegí EXACTAMENTE 5 fragmentos distintos que funcionen como reels por sí solos. Para este video, cada clip debe durar entre ${minDur} y ${maxDur} segundos. ${overlapRule}\n${editorialRules}\nPriorizá respuestas completas, frases memorables, datos concretos, consecuencias, explicaciones claras, emoción, sorpresa o humor según el contenido. Evitá saludos, presentaciones y relleno. Si incluís una pregunta, devolvé question_start y question_end exactos, y start debe coincidir con question_start. Si no hay pregunta útil, usá -1 en ambos. Categoría: ${S.category}. Modo: ${S.mode}. Pedido específico: ${$('#request').value.trim()||'ninguno'}. ${pol} Todos los tiempos deben estar dentro de 0 y ${total.toFixed(1)} segundos y ser absolutos desde el inicio del video. En boundary_check explicá brevemente por qué el comienzo es autosuficiente y por qué el final cierra la idea.`;
  const body={
    contents:[{parts:[
      {text:prompt},
      {file_data:{mime_type:fileInfo.mimeType||S.file.type||'video/mp4',file_uri:fileInfo.uri}}
    ]}],
    generationConfig:{
      temperature:0.25,
      responseMimeType:'application/json',
      responseSchema:{
        type:'OBJECT',
        properties:{
          clips:{
            type:'ARRAY',minItems:5,maxItems:5,
            items:{
              type:'OBJECT',
              properties:{
                title:{type:'STRING'},
                start:{type:'NUMBER'},
                end:{type:'NUMBER'},
                question_start:{type:'NUMBER'},
                question_end:{type:'NUMBER'},
                hook_end:{type:'NUMBER'},
                hook_closing_words:{type:'STRING'},
                opening_words:{type:'STRING'},
                closing_words:{type:'STRING'},
                boundary_check:{type:'STRING'},
                reason:{type:'STRING'}
              },
              required:['title','start','end','question_start','question_end','hook_end','hook_closing_words','opening_words','closing_words','boundary_check','reason']
            }
          }
        },
        required:['clips']
      }
    }
  };
  const models=['gemini-3.8-flash','gemini-3.6-flash','gemini-3.5-flash-lite'];
  let lastErr='', hadValidResponse=false;
  const normalizeClip=(c,i)=>{
    let st=Number(c.start), en=Number(c.end);
    if(!Number.isFinite(st))st=(i/5)*Math.max(0,total-minDur);
    if(!Number.isFinite(en))en=st+minDur;
    st=Math.max(0,Math.min(st,Math.max(0,total-1)));
    en=Math.max(st+.5,Math.min(en,total));
    if(en<=st){st=Math.max(0,Math.min(st,total-1));en=total}
    let qs=Number(c.question_start??-1), q=Number(c.question_end??-1);
    if(Number.isFinite(qs)&&Number.isFinite(q)&&qs>=0&&q>qs&&q<en) st=Math.max(0,Math.min(st,qs)); else qs=-1;
    if(!Number.isFinite(q)||q<=st||q>=en)q=-1;
    return {
      title:String(c.title||'Clip '+(i+1)),
      start:Number(st.toFixed(2)),
      end:Number(en.toFixed(2)),
      question_start:qs<0?-1:Number(qs.toFixed(2)),
      question_end:q<0?-1:Number(q.toFixed(2)),
      hook_end:Number(c.hook_end),
      hook_closing_words:String(c.hook_closing_words||''),
      opening_words:String(c.opening_words||''),
      closing_words:String(c.closing_words||''),
      boundary_check:String(c.boundary_check||''),
      reason:String(c.reason||''),
      selected_model:c.selected_model||''
    };
  };
  for(let mi=0;mi<models.length;mi++){
    const model=models[mi];
    const attempts=mi===0?2:1;
    for(let attempt=1;attempt<=attempts;attempt++){
      progress(20,`Gemini está analizando con ${model.replace('gemini-','')}…`,
        attempt>1?'Reintentando automáticamente…':
        mi>0?'Probando un modelo de respaldo…':
        `Buscando 5 clips de ${minDur}–${maxDur} s para este video.`);
      let r;
      try{
        r=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,{
          method:'POST',
          headers:{'x-goog-api-key':cfg().gemini,'Content-Type':'application/json'},
          body:JSON.stringify(body)
        });
      }catch(e){
        lastErr=String(e?.message||e);
        if(attempt<attempts){await new Promise(x=>setTimeout(x,2500));continue}
        break;
      }
      if(!r.ok){
        const raw=await r.text();
        lastErr=`${r.status} ${raw.slice(0,500)}`;
        if([429,500,502,503,504].includes(r.status)){
          if(attempt<attempts){await new Promise(x=>setTimeout(x,3000));continue}
          break;
        }
        throw new Error('Gemini análisis: '+lastErr);
      }
      hadValidResponse=true;
      const d=await r.json();
      const txt=(d.candidates?.[0]?.content?.parts||[]).map(x=>x.text||'').join('');
      let out;
      try{out=JSON.parse(txt)}catch{
        lastErr='Gemini no devolvió un JSON válido.';
        if(attempt<attempts)continue;
        break;
      }
      if(!Array.isArray(out.clips)||out.clips.length!==5){
        lastErr='Gemini no devolvió exactamente 5 clips.';
        if(attempt<attempts)continue;
        break;
      }
      progress(27,'Revisión editorial final…','Otro pase comprueba que ningún clip empiece o termine a mitad de una idea.');
      const reviewPrompt=`Actuá ahora como jefe de edición y auditá estas cinco selecciones preliminares contra el video completo:\n${JSON.stringify(out.clips)}\n\n${editorialRules}\nCorregí o reemplazá cualquier clip que empiece sin contexto, arranque a mitad de oración, termine con una frase inconclusa, alcance a incluir el comienzo del tema siguiente, tenga relleno o dependa de información exterior. Escuchá el audio alrededor de cada borde: start debe quedar apenas antes de la primera palabra completa y end entre 0.25 y 0.65 segundos después de la última palabra del cierre, antes de la oración siguiente. Conservá exactamente cinco clips fuertes y distintos dentro de ${minDur}–${maxDur} segundos. Si para cerrar bien una idea hay que elegir otro momento, reemplazalo. No apruebes mecánicamente la propuesta anterior. Reescribí opening_words y closing_words copiando literalmente lo que se oye en los límites finales. Devolvé únicamente el JSON solicitado.`;
      const reviewBody=JSON.parse(JSON.stringify(body));
      reviewBody.contents=[{parts:[
        {text:reviewPrompt},
        {file_data:{mime_type:fileInfo.mimeType||S.file.type||'video/mp4',file_uri:fileInfo.uri}}
      ]}];
      try{
        const rr=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,{
          method:'POST',
          headers:{'x-goog-api-key':cfg().gemini,'Content-Type':'application/json'},
          body:JSON.stringify(reviewBody)
        });
        if(rr.ok){
          const rd=await rr.json();
          const rtxt=(rd.candidates?.[0]?.content?.parts||[]).map(x=>x.text||'').join('');
          const reviewed=JSON.parse(rtxt);
          if(Array.isArray(reviewed.clips)&&reviewed.clips.length===5)out=reviewed;
        }
      }catch(e){console.warn('La revisión editorial usará la primera selección:',e)}
      const clips=out.clips.map((c,i)=>normalizeClip({...c,selected_model:model},i));
      if(clips.length===5)return clips;
    }
  }
  throw new Error(hadValidResponse
    ?'Gemini respondió, pero no pude convertir su selección en 5 clips válidos. Último detalle: '+lastErr
    :'Gemini no estuvo disponible después de varios intentos. Último error: '+lastErr);
}
async function geminiDelete(fileInfo){try{await fetch('https://generativelanguage.googleapis.com/v1beta/'+fileInfo.name,{method:'DELETE',headers:{'x-goog-api-key':cfg().gemini}})}catch{}}

class MiniFFmpeg{constructor(){this.worker=null;this.pending=new Map();this.loaded=false}async load(){if(this.loaded)return;const base='https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/umd';const [j,w]=await Promise.all([fetch(base+'/ffmpeg-core.js'),fetch(base+'/ffmpeg-core.wasm')]);const coreURL=URL.createObjectURL(await j.blob()),wasmURL=URL.createObjectURL(await w.blob());const ws=`let ffmpeg=null;async function loadCore(d){importScripts(d.coreURL);ffmpeg=await self.createFFmpegCore({mainScriptUrlOrBlob:d.coreURL+'#'+btoa(JSON.stringify({wasmURL:d.wasmURL}))});return true}function exec(d){ffmpeg.setTimeout(d.timeout??-1);ffmpeg.exec('-nostdin','-y',...d.args);const r=ffmpeg.ret;ffmpeg.reset();return r}self.onmessage=async e=>{const{id,type,data}=e.data;try{let o;if(type==='load')o=await loadCore(data);else if(type==='exec')o=exec(data);else if(type==='mkdir'){ffmpeg.FS.mkdir(data.path);o=true}else if(type==='mount'){ffmpeg.FS.mount(ffmpeg.FS.filesystems[data.fsType],data.options,data.mountPoint);o=true}else if(type==='read'){o=ffmpeg.FS.readFile(data.path);self.postMessage({id,ok:true,data:o},[o.buffer]);return}else if(type==='delete'){try{ffmpeg.FS.unlink(data.path)}catch{}o=true}else throw Error('ffmpeg');self.postMessage({id,ok:true,data:o})}catch(x){self.postMessage({id,ok:false,error:String(x.message||x)})}}`;const u=URL.createObjectURL(new Blob([ws],{type:'text/javascript'}));this.worker=new Worker(u);this.worker.onmessage=e=>{const m=e.data,p=this.pending.get(m.id);if(!p)return;this.pending.delete(m.id);m.ok?p.resolve(m.data):p.reject(Error(m.error))};await this.send('load',{coreURL,wasmURL});this.loaded=true}send(type,data,transfer=[]){const id=crypto.randomUUID();return new Promise((resolve,reject)=>{this.pending.set(id,{resolve,reject});this.worker.postMessage({id,type,data},transfer)})}exec(args,t=-1){return this.send('exec',{args,timeout:t})}mkdir(path){return this.send('mkdir',{path})}mount(fsType,options,mountPoint){return this.send('mount',{fsType,options,mountPoint})}read(path){return this.send('read',{path})}del(path){return this.send('delete',{path})}terminate(){try{this.worker?.terminate()}catch{}this.worker=null;this.loaded=false}}
async function getFF(){if(!S.ff)S.ff=new MiniFFmpeg();await S.ff.load();if(!S.mounted){try{await S.ff.mkdir('/input')}catch{}await S.ff.mount('WORKERFS',{files:[S.file]},'/input');S.mounted=true}return S.ff}
function ext(){const x=S.file.name.toLowerCase();return x.endsWith('.mov')?'.mov':'.mp4'}
async function groqWords(audioBytes,index){progress(36+index*7,'Subtitulando clip '+(index+1)+'/5…','Whisper Large V3 está escuchando este fragmento.');const fd=new FormData();fd.append('file',new File([audioBytes],'clip.mp3',{type:'audio/mpeg'}));fd.append('model','whisper-large-v3');fd.append('language','es');fd.append('response_format','verbose_json');fd.append('timestamp_granularities[]','word');const r=await fetch('https://api.groq.com/openai/v1/audio/transcriptions',{method:'POST',headers:{Authorization:'Bearer '+cfg().groq},body:fd});if(!r.ok)throw new Error('Groq: '+r.status+' '+(await r.text()).slice(0,500));const d=await r.json();return (d.words||[]).map(w=>({word:String(w.word||'').trim(),start:Number(w.start)||0,end:Number(w.end)||0})).filter(w=>w.word)}
function inferQuestionEnd(words,declared=0){
  const valid=Number(declared);
  if(Number.isFinite(valid)&&valid>.7)return valid;
  const w=(words||[]).filter(x=>x&&String(x.word||'').trim());
  if(!w.length)return 0;
  const first=String(w.slice(0,5).map(x=>x.word).join(' ')).toLowerCase();
  const looksQuestion=/^(¿?\s*)?(qué|que|cómo|como|cuál|cual|cuándo|cuando|dónde|donde|quién|quien|por qué|por que|cuánto|cuanto|creés|crees|pensás|pensas|considerás|consideras|te parece|le parece|podés|podes|puede|hay|es verdad|qué pasa|que pasa)/i.test(first);
  const limit=Math.min(w.length,50);
  for(let i=0;i<limit;i++){
    const word=String(w[i].word||'');
    const end=Number(w[i].end)||0;
    if(end<1.2||end>14)continue;
    if(/[?¿]/.test(word))return end;
    const next=w[i+1];
    const gap=next?(Number(next.start||0)-end):0;
    if(looksQuestion&&gap>.65&&end>=2.0)return end;
  }
  return 0;
}
function cleanToken(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9ñü]+/g,'')}
function lcsLength(a,b){const row=new Array(b.length+1).fill(0);for(const x of a){let prev=0;for(let j=1;j<=b.length;j++){const old=row[j];row[j]=x===b[j-1]?prev+1:Math.max(row[j],row[j-1]);prev=old}}return row[b.length]}
function findQuotedWords(words,quote,preferredTime){
  const wanted=String(quote||'').split(/\s+/).map(cleanToken).filter(Boolean);
  if(wanted.length<2)return null;
  let best=null;
  for(let i=0;i<words.length;i++){
    for(let len=Math.max(2,wanted.length-2);len<=Math.min(words.length-i,wanted.length+3);len++){
      const got=words.slice(i,i+len).map(x=>cleanToken(x.word)).filter(Boolean);
      if(!got.length)continue;
      const matches=lcsLength(wanted,got),similarity=matches/Math.max(wanted.length,got.length);
      const midpoint=(Number(words[i].start)+Number(words[i+len-1].end))/2;
      const score=similarity-Math.min(.28,Math.abs(midpoint-preferredTime)*.018);
      if(!best||score>best.score)best={startIndex:i,endIndex:i+len-1,matches,similarity,score};
    }
  }
  return best&&best.matches>=2&&best.similarity>=.5?best:null;
}
function alignClipBoundaries(c,contextStart,contextWords){
  const desiredStart=c.start-contextStart,desiredEnd=c.end-contextStart;
  const first=findQuotedWords(contextWords,c.opening_words,desiredStart);
  const last=findQuotedWords(contextWords,c.closing_words,desiredEnd);
  let start=c.start,end=c.end;
  if(first&&Math.abs(Number(contextWords[first.startIndex].start)-desiredStart)<=4){
    start=contextStart+Math.max(0,Number(contextWords[first.startIndex].start)-.14);
  }
  if(last&&(!first||last.endIndex>=first.startIndex)&&Math.abs(Number(contextWords[last.endIndex].end)-desiredEnd)<=4){
    const spokenEnd=Number(contextWords[last.endIndex].end);
    const next=contextWords[last.endIndex+1];
    const gap=next?Math.max(.12,Number(next.start)-spokenEnd):.45;
    const hold=Math.min(.45,Math.max(.12,gap*.58));
    end=contextStart+spokenEnd+hold;
  }
  start=Math.max(0,Math.min(start,S.dur-.5));
  end=Math.min(S.dur,Math.max(start+.5,end));
  return{start:Number(start.toFixed(3)),end:Number(end.toFixed(3))};
}
function inferIntroEnd(words,declared=0,duration=0){
  const q=inferQuestionEnd(words,declared);
  if(q>.7&&q<duration-.7)return q;
  const usable=(words||[]).filter(w=>Number(w.end)>=1.6&&Number(w.end)<=Math.min(5.5,duration-1));
  if(!usable.length)return Math.min(3,Math.max(.8,duration*.2));
  for(const w of usable){
    const idx=words.indexOf(w),next=words[idx+1],gap=next?Number(next.start)-Number(w.end):0;
    if(/[.!?…]$/.test(String(w.word||''))||gap>.48)return Number(w.end);
  }
  return Number(usable.reduce((best,w)=>Math.abs(Number(w.end)-3.2)<Math.abs(Number(best.end)-3.2)?w:best).end);
}
async function prepareOne(c,i){
  const ff=await getFF();
  const contextStart=Math.max(0,c.start-3),contextEnd=Math.min(S.dur,c.end+3),contextDur=contextEnd-contextStart;
  const audio=`/a${i}.mp3`,source=`/s${i}.mp4`;
  let r=await ff.exec(['-ss',String(contextStart),'-t',String(contextDur),'-i','/input/'+S.file.name,'-vn','-ac','1','-ar','16000','-c:a','libmp3lame','-b:a','64k',audio],10*60*1000);
  if(r!==0)throw new Error('No pude extraer el audio del clip '+(i+1));
  const ab=await ff.read(audio);await ff.del(audio);
  const contextWords=await groqWords(ab,i);
  const aligned=alignClipBoundaries(c,contextStart,contextWords);
  const adjusted={...c,...aligned};
  const dur=adjusted.end-adjusted.start;
  const words=contextWords.map(w=>({...w,start:Number(w.start)+contextStart-adjusted.start,end:Number(w.end)+contextStart-adjusted.start})).filter(w=>w.end>=0&&w.start<=dur).map(w=>({...w,start:Math.max(0,w.start),end:Math.min(dur,w.end)}));
  const hookMatch=findQuotedWords(contextWords,c.hook_closing_words,c.hook_end-contextStart);
  const hookEnd=hookMatch&&Math.abs(contextWords[hookMatch.endIndex].end+contextStart-c.hook_end)<4
    ?contextWords[hookMatch.endIndex].end+contextStart:c.hook_end;
  const introEnd=hookEnd-adjusted.start;
  if(S.settings.qa&&(!Number.isFinite(introEnd)||introEnd<=.7||introEnd>=dur-.7)){
    throw new Error('El clip '+(i+1)+' no tiene una frase contundente inicial completa validada. Volvé a analizar el material.');
  }
  const srcStart=Math.max(0,adjusted.start-4),srcEnd=Math.min(S.dur,adjusted.end+4),srcDur=srcEnd-srcStart;
  progress(40+i*7,'Preparando fuente '+(i+1)+'/5…','Entrada B&N + audio telefónico; después transición suave a color.');
  r=await ff.exec(['-ss',String(srcStart),'-t',String(srcDur),'-i','/input/'+S.file.name,'-map','0:v:0','-map','0:a?','-c','copy','-movflags','+faststart',source],10*60*1000);
  if(r!==0){r=await ff.exec(['-ss',String(srcStart),'-t',String(srcDur),'-i','/input/'+S.file.name,'-vf','scale=1920:1920:force_original_aspect_ratio=decrease','-c:v','libx264','-preset','ultrafast','-crf','20','-c:a','aac','-b:a','160k','-movflags','+faststart',source],20*60*1000);if(r!==0)throw new Error('No pude preparar el video del clip '+(i+1))}
  const vb=await ff.read(source);await ff.del(source);
  const baseName=`${S.jobId}-source-${String(i+1).padStart(2,'0')}`;
  progress(44+i*7,'Subiendo fragmento '+(i+1)+'/5…','Lo divido en partes pequeñas para mantener la calidad sin superar el límite gratuito.');
  const bytes=vb instanceof Uint8Array?vb:new Uint8Array(vb);const PART=24*1024*1024,source_parts=[];
  for(let off=0,p=0;off<bytes.byteLength;off+=PART,p++){const chunk=bytes.slice(off,Math.min(bytes.byteLength,off+PART));const name=`${baseName}.part${String(p+1).padStart(3,'0')}`;const staged=await cloudUpload(name,new Blob([chunk],{type:'application/octet-stream'}),'application/octet-stream');source_parts.push(staged.url)}
  return{...adjusted,source_parts,source_offset:adjusted.start-srcStart,intro_end_rel:introEnd,words,captions:S.settings.captions,qa:S.settings.qa,reframe:S.settings.reframe}
}
async function stageAll(clips){const out=[];for(let i=0;i<5;i++)out.push(await prepareOne(clips[i],i));return out}
async function uploadManifest(clips){const enriched=[];for(let i=0;i<clips.length;i++){const name=`${S.jobId}-output-${String(i+1).padStart(2,'0')}.mp4`;const spec=await cloudUploadSpec(name,'output');enriched.push({...clips[i],output_path:spec.path,output_upload_url:spec.signed_url})}const manifest={version:2,job_id:S.jobId,created_at:new Date().toISOString(),category:S.category,clips:enriched};const up=await cloudUpload(`${S.jobId}-manifest.json`,new Blob([JSON.stringify(manifest)],{type:'application/octet-stream'}),'application/octet-stream','source');return up.url}
async function poll(){const started=Date.now();while(Date.now()-started<45*60*1000){const a=await listAssets(),done=a.find(x=>x.name===S.jobId+'-done.json');progress(done?98:88,done?'Render terminado':'Editando en GitHub…',done?'Preparando los 5 videos para mostrar…':'GitHub está procesando los cinco clips.');if(done){const results=[];for(let i=0;i<5;i++){const path=`jobs/${S.jobId}/output/${S.jobId}-output-${String(i+1).padStart(2,'0')}.mp4`;const dl=await cloud('download-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});results.push({name:`${S.jobId}-output-${String(i+1).padStart(2,'0')}.mp4`,url:dl.url})}await showOutputs(results);progress(100,'Listo','Los cinco videos están terminados.');return}await new Promise(r=>setTimeout(r,8000))}throw new Error('El render tardó demasiado. Revisá GitHub Actions.')}

async function showOutputs(items){const g=$('#grid');g.innerHTML='';for(let i=0;i<items.length;i++){const url=items[i].url,c=S.clips[i]||{};const el=document.createElement('article');el.className='clip';el.innerHTML=`<h4>${esc(c.title||'Clip '+(i+1))}</h4><p>${esc(c.reason||'')}</p>`;const v=document.createElement('video');v.controls=true;v.playsInline=true;v.preload='metadata';v.src=url;el.appendChild(v);const a=document.createElement('a');a.className='download';a.href=url;a.target='_blank';a.rel='noopener';a.download=`Varez_${String(i+1).padStart(2,'0')}_${(c.title||'clip').replace(/[^a-z0-9áéíóúñ_-]+/gi,'_')}.mp4`;a.textContent='Descargar MP4';el.appendChild(a);g.appendChild(el)}$('#results').style.display='block';$('#results').scrollIntoView({behavior:'smooth',block:'start'})}

$('#go').onclick=async()=>{if(!S.file)return alert('Primero elegí un video.');if(S.dur>1800)return alert('Máximo 30 minutos en esta beta.');if(!ensureConfig())return;$('#go').disabled=true;$('#results').style.display='none';S.jobId=crypto.randomUUID().replaceAll('-','').slice(0,16);try{await ensureRelease();const gf=await geminiUpload(S.file);let clips;try{clips=await geminiSelect(gf)}finally{geminiDelete(gf)}if(clips.length!==5)fail('No pude obtener cinco clips válidos.');S.clips=clips;progress(32,'Tengo los 5 momentos','Ahora preparo subtítulos y los fragmentos fuente.');const staged=await stageAll(clips);if(S.ff){S.ff.terminate();S.ff=null;S.mounted=false}const manifestUrl=await uploadManifest(staged);progress(82,'Mandando a edición remota…','GitHub FFmpeg va a producir los cinco MP4.');await dispatch(manifestUrl);await poll();try{await cloud('cleanup-source',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:S.jobId})})}catch{}}catch(e){progress(100,'Hubo un problema',e.message||String(e));$('#log').className='log error';alert(e.message||e)}finally{$('#go').disabled=false}};
ensureLogin();if(localStorage.getItem(LS.pin)==='053362'&&!ensureConfig())openSettings();
