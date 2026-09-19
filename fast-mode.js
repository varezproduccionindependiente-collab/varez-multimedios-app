(() => {
  const nativeFetch = window.fetch.bind(window);
  let cachedSelection = null;

  function isGeminiGenerate(url){
    return typeof url === 'string' &&
      url.includes('generativelanguage.googleapis.com/v1beta/models/') &&
      url.includes(':generateContent');
  }

  window.fetch = async function(input, init = {}){
    const rawUrl = typeof input === 'string' ? input : input?.url;
    if(!isGeminiGenerate(rawUrl)) return nativeFetch(input, init);

    const url = rawUrl.replace(/models\/gemini-[^:]+:generateContent/, 'models/gemini-3.6-flash:generateContent');
    const body = typeof init?.body === 'string' ? init.body : '';

    // The normal pipeline asks for a second editorial opinion after the first
    // selection. In fast mode we keep the first valid selection and avoid a
    // second Gemini round-trip.
    if(body.includes('Actuá como jefe de edición') && cachedSelection){
      return new Response(cachedSelection, {
        status: 200,
        headers: {'Content-Type':'application/json'}
      });
    }

    const response = await nativeFetch(url, {...init});
    if(response.ok && body.includes('Sos el editor senior de Varez Servicios para Multimedios')){
      try{ cachedSelection = await response.clone().text(); }catch{}
    }
    return response;
  };

  // Every manual run/retry starts the visible clip process from zero.
  document.addEventListener('click', event => {
    const button = event.target?.closest?.('#go');
    if(!button) return;
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
      log.textContent='Modo rápido fijo: Gemini 3.6 Flash, sin cambiar de método.';
      log.className='log';
    }
  }, true);
})();