(() => {
  const info = document.createElement('div');
  info.style.cssText = 'display:none;margin-top:12px;padding:11px 13px;border:1px solid #34342f;background:#111110;border-radius:9px;color:#c4f16a;font-size:11px;line-height:1.6';
  info.id = 'sourceInfo';
  document.querySelector('#urlpane')?.append(info);
  const url = document.querySelector('#url');
  let timer;
  url?.addEventListener('input', () => {
    clearTimeout(timer);
    const value = url.value.trim();
    if (!/^https?:\/\//i.test(value)) { info.style.display = 'none'; return; }
    info.style.display = 'block'; info.textContent = 'Bağlantı okunuyor · video başlığı, süresi ve kullanılabilir kalite seçenekleri aranıyor…';
    timer = setTimeout(async () => {
      try {
        const r = await fetch('/api/inspect?url=' + encodeURIComponent(value));
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'Bağlantı okunamadı');
        const mins = d.duration ? `${Math.floor(d.duration / 60)} dk ${Math.round(d.duration % 60)} sn` : 'Süre bilgisi alınamadı';
        info.textContent = `✓ ${d.title} · ${mins}${d.height ? ` · kaynak ${d.width}×${d.height}` : ''}${d.extractor ? ` · ${d.extractor}` : ''}`;
        window._clipDuration = d.duration || 0;
      } catch (e) { info.textContent = e.message; }
    }, 600);
  });
  document.querySelector('#file')?.addEventListener('change', () => {
    const f = document.querySelector('#file').files?.[0]; if (!f) return;
    const url = URL.createObjectURL(f), v = document.createElement('video'); v.preload = 'metadata';
    v.onloadedmetadata = () => {
      const d = v.duration, m = Math.floor(d / 60), s = Math.round(d % 60);
      const meta = document.querySelector('#filemeta');
      if (meta) meta.textContent += ` · ${m} dk ${s} sn · ${v.videoWidth}×${v.videoHeight}`;
      window._clipDuration = d; URL.revokeObjectURL(url);
    };
    v.onerror = () => URL.revokeObjectURL(url); v.src = url;
  });
  const cards = document.querySelector('#clips');
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    if (String(args[0]).includes('/api/jobs/')) {
      const parseJson = response.json.bind(response);
      response.json = async () => { const data = await parseJson(); if (data.clips) window._resultClips = data.clips; return data; };
    }
    return response;
  };
  if (cards) new MutationObserver(() => cards.querySelectorAll('.clip').forEach((card,index) => {
    const result = window._resultClips?.[index];
    if (result && !card.querySelector('.moment-reason')) {
      if (result.score) { const badge=document.createElement('span'); badge.textContent=`ÖNE ÇIKAN · ${result.score}/100`; badge.style.cssText='display:inline-block;margin-top:7px;color:#c4f16a;font-size:9px;letter-spacing:.7px'; card.prepend(badge); }
      if (result.reason) { const reason=document.createElement('div'); reason.className='moment-reason'; reason.textContent=`“${result.reason.slice(0,96)}${result.reason.length>96?'…':''}”`; reason.style.cssText='margin-top:7px;color:#aaa99f;font-size:10px;line-height:1.5'; card.insertBefore(reason,card.querySelector('video')); }
    }
    const video = card.querySelector('video'); const clip = card.querySelector('a[href$=".mp4"]');
    if (video && clip && !card.querySelector('.subtitle-link')) {
      const subtitle = document.createElement('a'); subtitle.className = 'subtitle-link';
      subtitle.style.cssText = 'display:block;margin-top:8px;color:#d5d3c9;text-decoration:none;font-size:11px';
      subtitle.textContent = 'Altyazı dosyasını indir';
      const index = [...cards.querySelectorAll('.clip')].indexOf(card) + 1;
      const match = clip.href.match(/^(.*)_klip_\d+\.mp4$/);
      if (match) { subtitle.href = `${match[1]}_klip_${String(index).padStart(2,'0')}.srt`; subtitle.download = ''; card.append(subtitle); }
    }
    const subtitle = card.querySelector('.subtitle-link');
    if (subtitle && !card.querySelector('.edit-caption')) {
      const edit = document.createElement('button'); edit.className = 'edit-caption'; edit.textContent = 'Altyazıyı düzelt';
      edit.style.cssText = 'margin-top:8px;border:1px solid #34342f;background:#191918;color:#c4f16a;border-radius:7px;padding:7px 9px;font-size:10px';
      const panel = document.createElement('div'); panel.hidden = true; panel.style.cssText = 'margin-top:8px';
      const area = document.createElement('textarea'); area.rows = 7; area.spellcheck = true;
      area.style.cssText = 'width:100%;resize:vertical;background:#10100f;border:1px solid #41413a;border-radius:7px;color:#eee;padding:9px;font:11px/1.5 monospace';
      const save = document.createElement('button'); save.textContent = 'Düzeltmeyi kaydet';
      save.style.cssText = 'margin-top:6px;background:#c4f16a;color:#181b11;border:0;border-radius:7px;padding:8px 10px;font-weight:700;font-size:10px';
      edit.onclick = async () => { panel.hidden = !panel.hidden; if (!area.value) { const r = await fetch(subtitle.href); area.value = await r.text(); } };
      save.onclick = async () => {
        const old = save.textContent; save.textContent = 'Kaydediliyor…';
        try { const name = subtitle.href.split('/').pop(); const r = await fetch('/api/outputs/' + encodeURIComponent(name), {method:'POST',headers:{'Content-Type':'text/plain;charset=utf-8'},body:area.value}); const d=await r.json(); if(!r.ok) throw new Error(d.error); save.textContent='Kaydedildi ✓'; }
        catch(e) { save.textContent=e.message; }
        setTimeout(()=>{if(save.textContent==='Kaydedildi ✓')save.textContent=old},1800);
      };
      panel.append(area, save); card.append(edit, panel);
    }
  })).observe(cards, { childList: true, subtree: true });
  const msg = document.querySelector('#jobmsg');
  const stages = document.createElement('div');
  stages.style.cssText = 'display:flex;gap:7px;flex-wrap:wrap;margin-top:10px';
  stages.innerHTML = ['Kaynağı al','Süreyi ölç','Konuşmayı yazıya dök','Anları sırala','Klipleri dışa aktar'].map((x,i)=>`<span data-stage="${i}" style="border:1px solid #333;border-radius:20px;padding:5px 8px;color:#828278;font-size:9px">${i+1} · ${x}</span>`).join('');
  msg?.after(stages);
  if (msg) new MutationObserver(() => {
    const t = msg.textContent.toLowerCase(); let done = 0;
    if (t.includes('indiriliyor') || t.includes('kaynak hazırlanıyor')) done = 1;
    if (t.includes('inceleniyor')) done = 2;
    if (t.includes('döküm') || t.includes('yazıya dökülüyor') || t.includes('whisper')) done = 3;
    if (t.includes('anlar sıralanıyor') || t.includes('klipler hazırlanıyor')) done = 4;
    if (t.includes('dışa aktarılıyor') || t.includes('hazır')) done = 5;
    stages.querySelectorAll('[data-stage]').forEach(x=>{ const i=Number(x.dataset.stage); x.style.color=i<done?'#c4f16a':i===done-1?'#f4f0df':'#828278'; x.style.borderColor=i<done?'#53652f':i===done-1?'#c4f16a':'#333'; });
  }).observe(msg, { childList: true, characterData: true, subtree: true });
})();
