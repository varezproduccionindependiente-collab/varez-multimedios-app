// Editorial decisions stay in the model; timing and job recovery are deterministic.
export const JOB_VERSION = 33;
export const MIN_CLIP_SECONDS = 30;
export const MAX_CLIP_SECONDS = 75;
export const MAX_SOURCE_SHARE = .82;
export const MIN_HOOK_SECONDS = 4.5;
export const MAX_HOOK_SECONDS = 9.5;
export const normalizeToken = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '');

export function cleanWords(words) {
  return (words || []).map(w => ({word:String(w.word || '').trim(), start:Number(w.start), end:Number(w.end)}))
    .filter(w => w.word && Number.isFinite(w.start) && Number.isFinite(w.end) && w.start >= 0 && w.end > w.start)
    .sort((a,b) => a.start - b.start);
}

export function normalizeSelection(raw, total) {
  if (!Array.isArray(raw) || raw.length > 5) throw new Error('La selección recibida no es válida.');
  const clips = [];
  for (const item of raw) {
    const start = Number(item.start), end = Number(item.end);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > total + .1 || end - start < 2) continue;
    // Never manufacture windows, pad to a quota or truncate a complete idea.
    if (clips.some(c => Math.max(0, Math.min(c.end,end)-Math.max(c.start,start)) / Math.min(c.end-c.start,end-start) > .8)) continue;
    clips.push({...item, start, end:Math.min(total,end), title:String(item.title || `Clip ${clips.length+1}`),
      question_start:-1, question_end:-1, hook_end:Number(item.hook_end)});
  }
  return clips;
}

export function findQuote(words, quote, preferredTime, edge='end') {
  const tokens = String(quote || '').split(/\s+/).map(normalizeToken).filter(Boolean);
  if (tokens.length < 2) return null;
  let best = null;
  // Match complete contiguous quotes first. A broad fuzzy match can include the next sentence.
  for (let i=0; i<=words.length-tokens.length; i++) {
    const actual = words.slice(i,i+tokens.length).map(w=>normalizeToken(w.word));
    const hits = tokens.filter((t,j)=>t===actual[j]).length;
    if (hits / tokens.length < .8 || tokens[0]!==actual[0] || tokens.at(-1)!==actual.at(-1)) continue;
    const at = edge==='start' ? words[i].start : words[i+tokens.length-1].end;
    const score = hits/tokens.length - (Number.isFinite(preferredTime) ? Math.min(.15,Math.abs(at-preferredTime)*.005) : 0);
    if (!best || score>best.score) best={first:i,last:i+tokens.length-1,score};
  }
  return best;
}

function beforeWord(words, index) {
  const w=words[index], prev=words[index-1];
  const gap=prev ? Math.max(0,w.start-prev.end) : w.start;
  return Math.max(0,w.start-Math.min(.14,gap*.5));
}
function afterWord(words, index) {
  const w=words[index], next=words[index+1];
  const gap=next ? Math.max(0,next.start-w.end) : .7;
  return w.end+Math.min(.4,gap*.5);
}
function rangePlan(c, words, contextStart, total, first, last, hookLast, requireHook, hookFirst=first) {
  if (![first,last].every(Number.isInteger) || first<0 || last>=words.length || first>=last) return null;
  if (requireHook && (!Number.isInteger(hookLast) || hookLast<hookFirst || hookLast>last || !Number.isInteger(hookFirst) || hookFirst<first)) return null;
  const start=contextStart+beforeWord(words,first), end=Math.min(total,contextStart+afterWord(words,last));
  const bodyDuration=end-start;
  const hs=requireHook && Number.isInteger(hookFirst) ? beforeWord(words,hookFirst) : 0;
  const he=requireHook && Number.isInteger(hookLast) ? afterWord(words,hookLast) : 0;
  const intro=requireHook ? he-hs : 0;
  // The model may suggest a whole interview even when the prompt asks for a reel.
  // Reject it here so the word-level repair pass has to choose one complete idea.
  if (bodyDuration<MIN_CLIP_SECONDS || bodyDuration>MAX_CLIP_SECONDS+.05 || (total>45 && bodyDuration/total>MAX_SOURCE_SHARE)) return null;
  if (requireHook && (intro<MIN_HOOK_SECONDS || intro>MAX_HOOK_SECONDS || intro>=bodyDuration-.7)) return null;
  return {...c,start,end,edit_style:"teaser",hook_start_rel:hs+contextStart-start,hook_end_rel:he+contextStart-start,hook_words:requireHook ? words.slice(hookFirst,hookLast+1).map(w=>({...w,start:w.start-hs,end:w.end-hs})) : [],hook_end:contextStart+(words[hookLast]?.end || 0),intro_end_rel:intro,
    opening_words:words.slice(first,Math.min(first+10,last+1)).map(w=>w.word).join(' '),
    closing_words:words.slice(Math.max(first,last-9),last+1).map(w=>w.word).join(' '),
    words:words.slice(first,last+1).map(w=>({...w,start:Math.max(0,w.start+contextStart-start),end:w.end+contextStart-start}))};
}

export function alignQuotes(c, words, contextStart, total, requireHook=true) {
  if (c.context_start_complete!==true || c.context_end_complete!==true) return null;
  if (requireHook && (c.hook_context_complete!==true || c.single_contiguous_hook!==true)) return null;
  const first=findQuote(words,c.opening_words,c.start-contextStart,'start');
  const last=findQuote(words,c.closing_words,c.end-contextStart);
  // A correct quote fixes an absolute/relative hook timestamp mixup as well as a missing timestamp.
  const hook=findQuote(words,c.hook_closing_words,Number(c.hook_end)-contextStart);
  const hookFirst=findQuote(words,c.hook_opening_words,Number(c.hook_start)-contextStart,"start");
  if (!first || !last || (requireHook && (!hook || (c.hook_opening_words && !hookFirst)))) return null;
  if (Math.abs(words[first.first].start+contextStart-c.start)>5 || Math.abs(words[last.last].end+contextStart-c.end)>5) return null;
  return rangePlan(c,words,contextStart,total,first.first,last.last,hook?.last,requireHook,hookFirst?.first ?? first.first);
}

export function planFromWordIds(c, words, contextStart, total, answer, requireHook=true) {
  if (answer?.usable!==true) return null;
  const first=answer.first_word, last=answer.last_word, hook=answer.hook_last_word;
  if (answer.complete_start!==true || answer.complete_end!==true ||
      (requireHook && (answer.protagonist_hook!==true || answer.hook_context_complete!==true || answer.single_contiguous_hook!==true))) return null;
  return rangePlan(c,words,contextStart,total,first,last,hook,requireHook,answer.hook_first_word ?? first);
}

export async function prepareCandidates(job, prepare, save=()=>{}) {
  for (let i=0; i<job.clips.length; i++) {
    if (['ready','skipped'].includes(job.entries[i]?.status)) continue;
    try {
      const clip=await prepare(job.clips[i],i);
      job.entries[i]=clip ? {status:'ready',clip} : {status:'skipped',reason:'No se pudo conservar una idea completa con el gancho solicitado.'};
    } catch(error) {
      job.entries[i]={status:'error',reason:String(error?.message || error)};
    }
    await save(job);
  }
  return job.entries.filter(e=>e?.status==='ready').map(e=>e.clip);
}

export function saveJob(storage,key,job) {
  storage.setItem(key,JSON.stringify(job));
}
export function loadJob(storage,key) {
  try {
    const j=JSON.parse(storage.getItem(key));
    return j?.version===JOB_VERSION && /^[a-f0-9]{16}$/.test(j.id) && Array.isArray(j.clips) && j.clips.length<=5 && Array.isArray(j.entries) ? j : null;
  } catch { return null; }
}
