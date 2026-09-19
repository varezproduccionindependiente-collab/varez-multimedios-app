(() => {
  localStorage.removeItem('varez_multimedios_job_v22');
  localStorage.removeItem('varez_multimedios_job_v22_previous');
  const nativeFetch = window.fetch.bind(window);
  let cachedSelection = null;

  function isGeminiGenerate(url){
    return typeof url === 'string' &&
      url.includes('generativelanguage.googleapis.com/v1beta/models/') &&
      url.includes(':generateContent');
  }

  function quotaWaitMs(text){
    const marker='Please retry in ';
    const p=String(text||'').indexOf(marker);
    if(p<0) return 15000;
    const n=parseFloat(String(text).slice(p+marker.length));
    return Math.max(1000, Math.ceil((Number.isFinite(n)?n:15)*1000)+500);
  }

  function setQuotaProgress(ms){
    const panel=document.querySelector('#progress');
    const pct=document.querySelector('#ppct');
    const bar=document.querySelector('#pbar');
    const label=document.querySelector('#plabel');
    const log=document.querySelector('#log');
    if(panel) panel.style.display='block';
    if(pct) pct.textContent='20%';
    if(bar) bar.style.width='20%';
    if(label) label.textContent='Esperando a Gemini…';
    if(log){
      log.textContent='Límite momentáneo. Reintento automático en '+Math.ceil(ms/1000)+' s con el mismo modelo.';
      log.className='log';
    }
  }

  window.fetch = async function(input, init = {}){
    const rawUrl = typeof input === 'string' ? input : input?.url;
    if(!isGeminiGenerate(rawUrl)) return nativeFetch(input, init);

    const url = rawUrl.replace(/models\/gemini-[^:]+:generateContent/, 'models/gemini-3.6-flash:generateContent');
    const body = typeof init?.body === 'string' ? init.body : '';

    if(body.includes('Actuá como jefe de edición') && cachedSelection){
      return new Response(cachedSelection, {
        status: 200,
        headers: {'Content-Type':'application/json'}
      });
    }

    let response = await nativeFetch(url, {...init});

    if(response.status===429){
      let raw='';
      try{ raw=await response.clone().text(); }catch{}
      const wait=quotaWaitMs(raw);
      setQuotaProgress(wait);
      await new Promise(resolve=>setTimeout(resolve,wait));
      response=await nativeFetch(url, {...init});

      if(response.status===429){
        return new Response(
          JSON.stringify({error:'Gemini sigue con límite momentáneo. Volvé a iniciar el análisis dentro de unos segundos.'}),
          {status:400,headers:{'Content-Type':'application/json'}}
        );
      }
    }

    if(response.ok && body.includes('Sos el editor senior de Varez Servicios para Multimedios')){
      try{ cachedSelection = await response.clone().text(); }catch{}
    }
    return response;
  };

  function cleanResumeUI(){
    const go=document.querySelector('#go');
    const notice=document.querySelector('#jobNotice');
    const newAnalysis=document.querySelector('#newAnalysis');
    const sub=document.querySelector('.head .sub');
    if(go && !go.disabled && go.textContent!=='Analizar y crear clips') go.textContent='Analizar y crear clips';
    if(notice && !notice.hidden) notice.hidden=true;
    if(newAnalysis && !newAnalysis.hidden) newAnalysis.hidden=true;
    if(sub && sub.textContent.includes('El avance se guarda')) sub.textContent='Hasta cinco clips con ideas completas. Cada análisis empieza desde cero.';
  }

  document.addEventListener('DOMContentLoaded', () => {
    cleanResumeUI();
    new MutationObserver(cleanResumeUI).observe(document.body,{subtree:true,childList:true,attributes:true,characterData:true});
  });

  document.addEventListener('click', event => {
    const button = event.target?.closest?.('#go');
    if(!button) return;

    // Before the app's own click handler runs, discard any previous failed/done job.
    const reset=document.querySelector('#newAnalysis');
    if(reset) reset.click();
    localStorage.removeItem('varez_multimedios_job_v22');

    const panel=document.querySelector('#progress');
    const pct=document.querySelector('#ppct');
    const bar=document.querySelector('#pbar');
    const label=document.querySelector('#plabel');
    const log=document.querySelector('#log');
    if(panel) panel.style.display='block';
    if(pct) pct.textContent='0%';
    if(bar) bar.style.width='0%';
    if(label) label.textContent='Iniciando desde cero…';
    if(log){
      log.textContent='Nuevo análisis. No se retomará ningún trabajo anterior.';
      log.className='log';
    }
  }, true);
})();