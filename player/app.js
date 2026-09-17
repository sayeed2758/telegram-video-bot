(() => {
  const qs = new URLSearchParams(location.search);
  const src = qs.get('src');
  const title = qs.get('title') || 'Video';
  const quality = qs.get('quality') || 'AUTO';
  const poster = qs.get('poster');

  const video = document.getElementById('video');
  const titleEl = document.getElementById('title');
  const detailTitle = document.getElementById('detailTitle');
  const qualityChip = document.getElementById('qualityChip');
  const meta = document.getElementById('meta');
  const stage = document.getElementById('stage');
  const bigPlay = document.getElementById('bigPlay');
  const playBtn = document.getElementById('playBtn');
  const seek = document.getElementById('seek');
  const current = document.getElementById('current');
  const duration = document.getElementById('duration');
  const muteBtn = document.getElementById('muteBtn');
  const speed = document.getElementById('speed');
  const loader = document.getElementById('loader');
  const message = document.getElementById('message');

  titleEl.textContent = title; detailTitle.textContent = title; qualityChip.textContent = quality;
  if (poster) video.poster = poster;

  const fmt = (s) => { if (!Number.isFinite(s)) return '00:00'; s = Math.max(0, Math.floor(s)); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60; return h ? `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`; };
  const showMessage = (text) => { message.textContent = text; message.classList.remove('hidden'); };
  const hideMessage = () => message.classList.add('hidden');
  const syncPlay = () => { const p = !video.paused; playBtn.textContent = p ? '❚❚' : '▶'; bigPlay.classList.toggle('hidden', p); };
  const togglePlay = () => video.paused ? video.play().catch(()=>{}) : video.pause();

  if (!src) { showMessage('No video source was provided.'); bigPlay.classList.add('hidden'); loader.classList.add('hidden'); return; }
  video.src = src;
  loader.classList.remove('hidden');
  meta.textContent = `${quality} • Loading video`;

  ['loadedmetadata','canplay'].forEach(ev => video.addEventListener(ev, () => { loader.classList.add('hidden'); hideMessage(); meta.textContent = `${quality} • ${fmt(video.duration)}`; duration.textContent = fmt(video.duration); }));
  video.addEventListener('waiting', ()=>loader.classList.remove('hidden'));
  video.addEventListener('playing', ()=>{loader.classList.add('hidden'); syncPlay();});
  video.addEventListener('pause', syncPlay);
  video.addEventListener('play', syncPlay);
  video.addEventListener('timeupdate', ()=>{ current.textContent=fmt(video.currentTime); seek.value=video.duration ? (video.currentTime/video.duration)*100 : 0; });
  video.addEventListener('error', ()=>{ loader.classList.add('hidden'); showMessage('The video could not be loaded in this browser. Try again or use the original stream link.'); });

  bigPlay.addEventListener('click', togglePlay); playBtn.addEventListener('click', togglePlay);
  document.getElementById('back10').addEventListener('click', ()=>{ video.currentTime=Math.max(0, video.currentTime-10); });
  document.getElementById('forward10').addEventListener('click', ()=>{ video.currentTime=Math.min(video.duration || video.currentTime+10, video.currentTime+10); });
  seek.addEventListener('input', ()=>{ if (video.duration) video.currentTime=(Number(seek.value)/100)*video.duration; });
  muteBtn.addEventListener('click', ()=>{ video.muted=!video.muted; muteBtn.textContent=video.muted?'🔇':'🔊'; });
  speed.addEventListener('change', ()=>{ video.playbackRate=Number(speed.value); });
  document.getElementById('fullscreenBtn').addEventListener('click', async()=>{ if (document.fullscreenElement) return document.exitFullscreen(); try { await stage.requestFullscreen(); } catch {} });
  document.getElementById('pipBtn').addEventListener('click', async()=>{ try { if (document.pictureInPictureElement) await document.exitPictureInPicture(); else if (document.pictureInPictureEnabled) await video.requestPictureInPicture(); } catch {} });
  document.getElementById('backBtn').addEventListener('click', ()=>{ if (history.length > 1) history.back(); else location.href='about:blank'; });

  let timer;
  const resetTimer=()=>{ stage.classList.remove('idle'); clearTimeout(timer); timer=setTimeout(()=>stage.classList.add('idle'), 2800); };
  stage.addEventListener('mousemove', resetTimer); stage.addEventListener('touchstart', resetTimer, {passive:true}); resetTimer();
  document.getElementById('moreBtn').addEventListener('click', ()=>showMessage('Use the quality buttons in Telegram to switch video quality.'));
})();
