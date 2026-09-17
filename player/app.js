(() => {
  const qs = new URLSearchParams(location.search);
  const src = qs.get('src');
  const title = qs.get('title') || 'Video';
  const initialQuality = qs.get('quality') || 'AUTO';
  const poster = qs.get('poster');
  const downloadUrl = qs.get('download') || src || '';
  const attachmentUrl = qs.get('attachment') || '';

  const decodeBase64Url = (value) => {
    try {
      let b64 = value.replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      return new TextDecoder().decode(bytes);
    } catch (_) {
      return '';
    }
  };

  let qualityMap = {};
  const encodedQualities = qs.get('qualities');
  if (encodedQualities) {
    try {
      const parsed = JSON.parse(decodeBase64Url(encodedQualities));
      if (parsed && typeof parsed === 'object') qualityMap = parsed;
    } catch (_) {}
  }

  const normalizeQualityMap = (map) => {
    const out = {};
    Object.entries(map || {}).forEach(([key, value]) => {
      if (typeof key === 'string' && typeof value === 'string' && value.trim()) out[key.toLowerCase()] = value.trim();
    });
    return out;
  };
  qualityMap = normalizeQualityMap(qualityMap);

  const video = document.getElementById('video');
  const titleEl = document.getElementById('title');
  const detailTitle = document.getElementById('detailTitle');
  const qualityChip = document.getElementById('qualityChip');
  const qualityValue = document.getElementById('qualityValue');
  const meta = document.getElementById('meta');
  const stage = document.getElementById('stage');
  const bigPlay = document.getElementById('bigPlay');
  const playBtn = document.getElementById('playBtn');
  const seek = document.getElementById('seek');
  const current = document.getElementById('current');
  const duration = document.getElementById('duration');
  const muteBtn = document.getElementById('muteBtn');
  const loader = document.getElementById('loader');
  const message = document.getElementById('message');
  const settingsMenu = document.getElementById('settingsMenu');
  const moreMenu = document.getElementById('moreMenu');
  const speedChoices = document.getElementById('speedChoices');
  const qualityChoices = document.getElementById('qualityChoices');
  const speedOpen = document.getElementById('speedOpen');
  const qualityOpen = document.getElementById('qualityOpen');
  const downloadBtn = document.getElementById('downloadBtn');

  titleEl.textContent = title;
  detailTitle.textContent = title;
  if (poster) video.poster = poster;

  const preferredQuality = ['1080p', '720p', '480p', '360p'];
  const availableQualities = Object.keys(qualityMap).sort((a, b) => {
    const ai = preferredQuality.indexOf(a), bi = preferredQuality.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });

  const currentQualityFromUrl = initialQuality && initialQuality.toLowerCase() !== 'auto' ? initialQuality.toLowerCase() : '';
  let currentQuality = currentQualityFromUrl && qualityMap[currentQualityFromUrl]
    ? currentQualityFromUrl
    : (qualityMap[initialQuality.toLowerCase()] ? initialQuality.toLowerCase() : 'auto');

  if (currentQuality === 'auto' && availableQualities.length) currentQuality = availableQualities[0];

  const displayQuality = () => currentQuality && currentQuality !== 'auto' ? currentQuality.toUpperCase() : 'AUTO';
  qualityChip.textContent = displayQuality();
  qualityValue.textContent = displayQuality() === 'AUTO' ? 'Auto' : displayQuality();

  const fmt = (seconds) => {
    if (!Number.isFinite(seconds)) return '00:00';
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h ? `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}` : `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
  };
  const showMessage = (text) => { message.textContent = text; message.classList.remove('hidden'); };
  const hideMessage = () => message.classList.add('hidden');
  const syncPlay = () => {
    const playing = !video.paused;
    playBtn.textContent = playing ? '❚❚' : '▶';
    bigPlay.classList.toggle('hidden', playing);
  };
  const togglePlay = () => video.paused ? video.play().catch(() => {}) : video.pause();

  const setSource = async (url, qualityLabel = 'AUTO') => {
    if (!url) return;
    const wasPlaying = !video.paused;
    const resumeAt = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    loader.classList.remove('hidden');
    hideMessage();
    currentQuality = qualityLabel && qualityLabel.toLowerCase() !== 'auto' ? qualityLabel.toLowerCase() : 'auto';
    qualityChip.textContent = displayQuality();
    qualityValue.textContent = displayQuality() === 'AUTO' ? 'Auto' : displayQuality();
    meta.textContent = `${displayQuality()} • Loading video`;

    video.src = url;
    video.load();

    const onLoaded = async () => {
      video.removeEventListener('loadedmetadata', onLoaded);
      try {
        if (resumeAt > 0 && resumeAt < video.duration) video.currentTime = resumeAt;
      } catch (_) {}
      if (wasPlaying) {
        try { await video.play(); } catch (_) {}
      }
    };
    video.addEventListener('loadedmetadata', onLoaded, { once: true });
  };

  const closePopups = () => {
    settingsMenu.classList.add('hidden');
    moreMenu.classList.add('hidden');
    speedChoices.classList.add('hidden');
    qualityChoices.classList.add('hidden');
  };

  if (!src) {
    showMessage('No video source was provided.');
    bigPlay.classList.add('hidden');
    loader.classList.add('hidden');
    return;
  }

  if (downloadUrl) downloadBtn.href = downloadUrl;
  else downloadBtn.classList.add('disabled');

  const buildQualityChoices = () => {
    qualityChoices.innerHTML = '';
    if (!availableQualities.length) {
      const empty = document.createElement('div');
      empty.className = 'quality-empty';
      empty.textContent = 'Quality selection is not available for this video.';
      qualityChoices.appendChild(empty);
      return;
    }
    const autoBtn = document.createElement('button');
    autoBtn.textContent = 'Auto';
    autoBtn.dataset.quality = 'auto';
    qualityChoices.appendChild(autoBtn);
    availableQualities.forEach((quality) => {
      const button = document.createElement('button');
      button.textContent = quality.toUpperCase();
      button.dataset.quality = quality;
      qualityChoices.appendChild(button);
    });
  };
  buildQualityChoices();

  const initialSrc = currentQuality !== 'auto' && qualityMap[currentQuality] ? qualityMap[currentQuality] : src;
  setSource(initialSrc, currentQuality === 'auto' ? 'AUTO' : currentQuality);

  video.addEventListener('loadedmetadata', () => {
    loader.classList.add('hidden');
    hideMessage();
    duration.textContent = fmt(video.duration);
    meta.textContent = `${displayQuality()} • ${fmt(video.duration)}`;
  });
  video.addEventListener('canplay', () => loader.classList.add('hidden'));
  video.addEventListener('waiting', () => loader.classList.remove('hidden'));
  video.addEventListener('playing', () => { loader.classList.add('hidden'); syncPlay(); });
  video.addEventListener('pause', syncPlay);
  video.addEventListener('play', syncPlay);
  video.addEventListener('timeupdate', () => {
    current.textContent = fmt(video.currentTime);
    seek.value = video.duration ? (video.currentTime / video.duration) * 100 : 0;
  });
  video.addEventListener('error', () => {
    loader.classList.add('hidden');
    showMessage('The video could not be loaded in this browser. Try Reload or the original stream link.');
  });

  bigPlay.addEventListener('click', togglePlay);
  playBtn.addEventListener('click', togglePlay);
  document.getElementById('back10').addEventListener('click', () => { video.currentTime = Math.max(0, video.currentTime - 10); });
  document.getElementById('forward10').addEventListener('click', () => { video.currentTime = Math.min(video.duration || video.currentTime + 10, video.currentTime + 10); });
  seek.addEventListener('input', () => { if (video.duration) video.currentTime = (Number(seek.value) / 100) * video.duration; });
  muteBtn.addEventListener('click', () => { video.muted = !video.muted; muteBtn.textContent = video.muted ? '🔇' : '🔊'; });
  document.getElementById('fullscreenBtn').addEventListener('click', async () => {
    if (document.fullscreenElement) return document.exitFullscreen();
    try { await stage.requestFullscreen(); } catch (_) {}
  });
  document.getElementById('pipBtn').addEventListener('click', async () => {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else if (document.pictureInPictureEnabled) await video.requestPictureInPicture();
    } catch (_) {}
  });
  document.getElementById('backBtn').addEventListener('click', () => { if (history.length > 1) history.back(); else location.href = 'about:blank'; });

  document.getElementById('settingsBtn').addEventListener('click', (event) => {
    event.stopPropagation();
    moreMenu.classList.add('hidden');
    settingsMenu.classList.toggle('hidden');
    speedChoices.classList.add('hidden');
    qualityChoices.classList.add('hidden');
  });

  document.getElementById('moreBtn').addEventListener('click', (event) => {
    event.stopPropagation();
    settingsMenu.classList.add('hidden');
    moreMenu.classList.toggle('hidden');
  });

  speedOpen.addEventListener('click', (event) => {
    event.stopPropagation();
    qualityChoices.classList.add('hidden');
    speedChoices.classList.toggle('hidden');
  });

  speedChoices.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-speed]');
    if (!button) return;
    const value = Number(button.dataset.speed);
    video.playbackRate = value;
    speedOpen.innerHTML = `${value}× <span>›</span>`;
    speedChoices.classList.add('hidden');
  });

  qualityOpen.addEventListener('click', (event) => {
    event.stopPropagation();
    speedChoices.classList.add('hidden');
    qualityChoices.classList.toggle('hidden');
  });

  qualityChoices.addEventListener('click', async (event) => {
    const button = event.target.closest('button[data-quality]');
    if (!button) return;
    const selected = button.dataset.quality;
    if (selected === 'auto') {
      currentQuality = 'auto';
      await setSource(src, 'AUTO');
    } else if (qualityMap[selected]) {
      await setSource(qualityMap[selected], selected);
    }
    qualityChoices.classList.add('hidden');
  });

  document.getElementById('reloadBtn').addEventListener('click', async () => {
    moreMenu.classList.add('hidden');
    const pos = Number.isFinite(video.currentTime) ? video.currentTime : 0;
    const wasPlaying = !video.paused;
    video.load();
    try {
      await new Promise((resolve) => {
        const handler = () => { video.removeEventListener('loadedmetadata', handler); resolve(); };
        video.addEventListener('loadedmetadata', handler, { once: true });
      });
      if (pos > 0 && pos < video.duration) video.currentTime = pos;
      if (wasPlaying) await video.play();
    } catch (_) {}
  });

  document.getElementById('attachmentBtn').addEventListener('click', async () => {
    moreMenu.classList.add('hidden');
    const target = attachmentUrl || src;
    if (!target) return;
    try {
      if (navigator.share) {
        await navigator.share({ title, text: title, url: target });
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(target);
        showMessage('Link copied.');
        setTimeout(hideMessage, 1600);
      } else {
        window.open(target, '_blank', 'noopener');
      }
    } catch (_) {}
  });

  document.addEventListener('click', (event) => {
    if (!event.target.closest('#settingsMenu') && !event.target.closest('#settingsBtn')) settingsMenu.classList.add('hidden');
    if (!event.target.closest('#moreMenu') && !event.target.closest('#moreBtn')) moreMenu.classList.add('hidden');
  });

  let timer;
  const resetTimer = () => {
    stage.classList.remove('idle');
    clearTimeout(timer);
    timer = setTimeout(() => stage.classList.add('idle'), 2800);
  };
  stage.addEventListener('mousemove', resetTimer);
  stage.addEventListener('touchstart', resetTimer, { passive: true });
  resetTimer();
})();