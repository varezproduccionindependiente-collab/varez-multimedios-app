(() => {
  localStorage.removeItem('varez_multimedios_job_v22');
  localStorage.removeItem('varez_multimedios_job_v22_previous');
  const nativeFetch = window.fetch.bind(window);

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
      log.textContent='Límite momentáneo. Reintento automático en '+Math.ceil(ms/1000)+' s; si sigue ocupado, se probará otro modelo.';
      log.className='log';
    }
  }

  window.fetch = async function(input, init = {}){
    const rawUrl = typeof input === 'string' ? input : input?.url;
    if(!isGeminiGenerate(rawUrl)) return nativeFetch(input, init);

    // Respect the model selected by app.js. Rewriting every URL here used to
    // defeat the fallback chain by sending every attempt to the same model.
    let response = await nativeFetch(input, {...init});

    if(response.status===429){
      let raw='';
      try{ raw=await response.clone().text(); }catch{}
      const wait=quotaWaitMs(raw);
      setQuotaProgress(wait);
      await new Promise(resolve=>setTimeout(resolve,wait));
      response=await nativeFetch(input, {...init});
    }
    return response;
  };

})();
