// ==UserScript==
// @name         whisper-subs: Local Subtitle Loader + Live Transcription
// @namespace    https://github.com/whisper-subs
// @version      2.0.0
// @description  Load local SRT files + live transcription with model selection for YouTube
// @match        *://www.youtube.com/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_addStyle
// @connect      localhost
// @run-at       document-end
// ==/UserScript==

(function() {
  'use strict';

  // ========================================================================
  // Config & State
  // ========================================================================

  const DEFAULT_CONFIG = {
    apiBase: 'http://localhost:8000',
    syncOffset: 0,
    fontSize: '18px',
    fontFamily: 'system-ui, sans-serif',
    color: '#fff',
    background: 'rgba(0,0,0,0.75)',
    textShadow: '2px 2px 4px #000',
    padding: '6px 12px',
    borderRadius: '6px',
    lineHeight: '1.4',
    maxWidth: '90%',
  };

  const MODEL_PRESETS = {
    // Local faster-whisper models
    'tiny':       { type: 'local',  size: '39 MB',  speed: '~6x',  lang: 'multi' },
    'base':       { type: 'local',  size: '74 MB',  speed: '~4x',  lang: 'multi' },
    'small':      { type: 'local',  size: '244 MB', speed: '~2x',  lang: 'multi' },
    'medium':     { type: 'local',  size: '769 MB', speed: '~1x',  lang: 'multi' },
    'large-v3':   { type: 'local',  size: '1550 MB',speed: '~0.5x',lang: 'multi' },
    'large-v3-turbo': { type: 'local', size: '809 MB', speed: '~2x', lang: 'multi' },
    // Distil models (faster)
    'distil-small.en':   { type: 'local', size: '166 MB', speed: '~4x', lang: 'en' },
    'distil-medium.en':  { type: 'local', size: '399 MB', speed: '~2x', lang: 'en' },
    'distil-large-v3':   { type: 'local', size: '756 MB', speed: '~1x', lang: 'multi' },
    // Adapter models (cloud/local)
    'sherpa:parakeet-tdt-0.6b-v3': { type: 'adapter', provider: 'sherpa-onnx', lang: 'multi', note: 'Fast streaming' },
    'sherpa:parakeet-tdt-0.6b':    { type: 'adapter', provider: 'sherpa-onnx', lang: 'multi' },
    'sherpa:parakeet-rnnt-1.1b':   { type: 'adapter', provider: 'sherpa-onnx', lang: 'multi', note: 'More accurate' },
    'parakeet:parakeet-ctc-1.1b':  { type: 'adapter', provider: 'parakeet', lang: 'en', note: 'NVIDIA Parakeet CTC' },
    'parakeet:parakeet-rnnt-1.1b': { type: 'adapter', provider: 'parakeet', lang: 'en', note: 'NVIDIA Parakeet RNNT' },
    'groq:whisper-large-v3':       { type: 'cloud', provider: 'groq', lang: 'multi', note: 'Fast cloud' },
    'groq:whisper-large-v3-turbo': { type: 'cloud', provider: 'groq', lang: 'multi' },
    'deepgram:nova-3':             { type: 'cloud', provider: 'deepgram', lang: 'multi', note: 'Nova-3' },
    'deepgram:nova-2':             { type: 'cloud', provider: 'deepgram', lang: 'multi' },
    'chirp:chirp_2':               { type: 'cloud', provider: 'google', lang: 'multi', note: 'Google Chirp 2' },
    'hf:openai/whisper-large-v3':  { type: 'cloud', provider: 'huggingface', lang: 'multi' },
    'voxtral:voxtral-mini':        { type: 'local', size: '1.5 GB', lang: 'multi', note: 'Voxtral mini' },
    'moonshine:moonshine/base':    { type: 'local', size: '200 MB', lang: 'en', note: 'Fast mobile' },
    'whisperx:large-v3':           { type: 'local', size: '1.5 GB', lang: 'multi', note: 'WhisperX with alignment' },
  };

  // Runtime state
  const state = {
    config: { ...DEFAULT_CONFIG, ...JSON.parse(GM_getValue('ws_config', '{}')) },
    srtMap: new Map(),
    dirHandle: null,
    video: null,
    overlay: null,
    syncOffset: 0,
    liveMode: false,
    liveTaskId: null,
    liveSSE: null,
    liveWS: null,
    model: 'sherpa:parakeet-tdt-0.6b-v3',
    modelConfig: {
      device: 'cpu',
      computeType: 'int8',
      cpuThreads: 4,
      vadFilter: false,
      language: 'en',
    },
    stylesInjected: false,
  };

  // ========================================================================
  // Helpers
  // ========================================================================

  function saveConfig() {
    GM_setValue('ws_config', JSON.stringify(state.config));
  }

  function parseSRT(text) {
    const cues = [];
    const blocks = text.trim().split(/\r?\n\r?\n/);
    for (const block of blocks) {
      const lines = block.trim().split(/\r?\n/);
      if (lines.length < 2) continue;
      let i = lines[0].trim().match(/^\d+$/) ? 1 : 0;
      const timeMatch = lines[i]?.match(
        /(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})/
      );
      if (!timeMatch) continue;
      const start = parseTime(timeMatch[1]);
      const end = parseTime(timeMatch[2]);
      const text = lines.slice(i + 1).join('\n').trim();
      if (text) cues.push({ start, end, text });
    }
    return cues.sort((a, b) => a.start - b.start);
  }

  function parseTime(str) {
    const [time, ms] = str.replace(',', '.').split('.');
    const parts = time.split(':').map(Number);
    const secs = parts.length === 3 ? parts[0]*3600 + parts[1]*60 + parts[2]
                  : parts.length === 2 ? parts[0]*60 + parts[1]
                  : Number(parts[0]);
    return secs + (Number(ms)||0)/1000;
  }

  function toWebVTT(cues) {
    let vtt = 'WEBVTT\n\n';
    for (let i=0;i<cues.length;i++) {
      vtt+=`${i+1}\n${fmt(cues[i].start)} --> ${fmt(cues[i].end)}\n${cues[i].text}\n\n`;
    }
    return vtt;
  }

  function fmt(s) {
    const h=Math.floor(s/3600).toString().padStart(2,'0');
    const m=Math.floor((s%3600)/60).toString().padStart(2,'0');
    const s=Math.floor(s%60).toString().padStart(2,'0');
    const ms=Math.floor((s%1)*1000).toString().padStart(3,'0');
    return `${h}:${m}:${s}.${ms}`;
  }

  function getVideoId() {
    const u=new URL(window.location.href);
    return u.searchParams.get('v') || u.pathname.split('/').pop();
  }

  function getVideoElement() {
    return document.querySelector('video.html5-main-video, video.video-stream');
  }

  function waitForVideo() {
    return new Promise(r=>{ const c=()=>{const v=getVideoElement();v?resolve(v):setTimeout(c,200);};c();});
  }

  function toWebVTT(cues) {
    let v='WEBVTT\n\n';
    for(let i=0;i<cues.length;i++){
      v+=`${i+1}\n${fmt(cues[i].start)} --> ${fmt(cues[i].end)}\n${cues[i].text}\n\n`;
    }
    return v;
  }
  function fmt(s){const h=Math.floor(s/3600).toString().padStart(2,'0');const m=Math.floor((s%3600)/60).toString().padStart(2,'0');const s=Math.floor(s%60).toString().padStart(2,'0');const ms=Math.floor((s%1)*1000).toString().padStart(3,'0');return `${h}:${m}:${s}.${ms}`;}

  // ========================================================================
  // Subtitle Overlay
  // ========================================================================

  class SubtitleOverlay {
    constructor(video) {
      this.video=video;this.cues=[];this.track=null;this.overlay=null;this.currentIdx=-1;
      this.syncOffset=0;this.enabled=true;this.cleanupFns=[];
      this.createOverlay();this.injectTrack();this.startSync();this.watchForReplacement();
    }
    createOverlay(){
      this.overlay=document.createElement('div');this.overlay.id='ws-overlay';
      this.overlay.style.cssText=`
        position:absolute;bottom:70px;left:50%;transform:translateX(-50%);
        pointer-events:none;z-index:2147483647;max-width:90%;text-align:center;
        font-size:${this.fontSize||'18px'};font-family:${this.fontFamily||'system-ui,sans-serif'};
        color:#fff;background:rgba(0,0,0,.75);text-shadow:2px 2px 4px #000;
        padding:6px 12px;border-radius:6px;line-height:1.4;max-width:90%;
        white-space:pre-wrap;word-wrap:break-word;opacity:0;transition:opacity .2s;
      `;
      const c=this.video.parentElement;
      if(c){const s=getComputedStyle(c);if(s.position==='static')c.style.position='relative';c.appendChild(this.overlay);}
      else{this.overlay.style.position='fixed';this.overlay.style.bottom='90px';document.body.appendChild(this.overlay);}
    }
    injectTrack(){
      if(!this.cues.length)return;
      const vtt='WEBVTT\n\n'+this.cues.map((c,i)=>`${i+1}\n${fmt(c.start)} --> ${fmt(c.end)}\n${c.text}\n\n`).join('');
      const blob=new Blob([vtt],{type:'text/vtt'}),url=URL.createObjectURL(blob);
      if(this.track){URL.revokeObjectURL(this.track.src);this.track.remove();}
      this.track=document.createElement('track');
      this.track.kind='subtitles';this.track.label='whisper-subs';this.track.srclang='en';this.track.default=true;this.track.src=url;
      this.video.appendChild(this.track);
    }
    setCues(c){this.cues=c;this.injectTrack();}
    set fontSize(v){this.fontSize=v;if(this.overlay)this.overlay.style.fontSize=v;}
    set fontFamily(v){this.fontFamily=v;if(this.overlay)this.overlay.style.fontFamily=v;}
    startSync(){
      const tick=()=>{if(!this.enabled||!this.video)return;
        const t=this.video.currentTime+this.syncOffset/1000;
        let idx=-1;for(let i=0;i<this.cues.length;i++){if(this.cues[i].start<=t&&t<=this.cues[i].end){idx=i;break;}}
        if(idx!==this.currentIdx){this.currentIdx=idx;this.render();}
        if(this.enabled)requestAnimationFrame(tick);
      };requestAnimationFrame(tick);
    }
    render(){if(!this.overlay)return;if(this.currentIdx>=0){this.overlay.textContent=this.cues[this.currentIdx].text;this.overlay.style.opacity='1';}else this.overlay.style.opacity='0';}
    setSyncOffset(ms){this.syncOffset=ms;}
    setEnabled(v){this.enabled=v;if(this.overlay)this.overlay.style.display=v?'block':'none';}
    destroy(){this.cleanupFns.forEach(f=>f());if(this.track){URL.revokeObjectURL(this.track.src);this.track.remove();}if(this.overlay)this.overlay.remove();this.enabled=false;}
    watchForReplacement(){
      this.observer=new MutationObserver(()=>{const v=getVideoElement();if(v&&v!==this.video){this.destroy();controller.init();}});
      this.observer.observe(document.body,{childList:true,subtree:true});
      this.cleanupFns.push(()=>this.observer?.disconnect());
    }
  }

  // ========================================================================
  // File handling (File System Access API + drag-drop)
  // ========================================================================

  async function pickSRTDirectory() {
    if (!window.showDirectoryPicker) throw new Error('File System Access API unavailable');
    return window.showDirectoryPicker({ mode: 'read' });
  }

  async function readSRTsFromHandle(handle) {
    const map = new Map();
    for await (const [name, entry] of handle.entries()) {
      if (entry.kind === 'file' && name.toLowerCase().endsWith('.srt')) {
        const file = await entry.getFile();
        const text = await file.text();
        const videoId = extractVideoIdFromFilename(name);
        if (videoId && !map.has(videoId)) map.set(videoId, { path: name, content: text });
      }
    }
    return map;
  }

  function extractVideoIdFromFilename(name) {
    const m = name.match(/([a-zA-Z0-9_-]{11})/);
    return m ? m[1] : null;
  }

  async function loadFromDirectoryPicker() {
    try {
      const handle = await pickSRTDirectory();
      return await readSRTsFromHandle(handle);
    } catch (e) {
      if (e.name !== 'AbortError') console.warn('[ws] picker failed:', e);
      return new Map();
    }
  }

  function setupDragDrop() {
    const zone = document.createElement('div');
    zone.id = 'ws-dropzone';
    zone.style.cssText = `
      position:fixed;top:10px;right:10px;z-index:2147483647;padding:8px 12px;
      background:rgba(0,0,0,.8);color:#fff;border-radius:6px;font:12px monospace;
      cursor:pointer;border:2px dashed #555;transition:border-color .2s;
    `;
    zone.textContent = 'Drop SRT folder here';
    document.body.appendChild(zone);
    zone.ondragover = e => { e.preventDefault(); zone.style.borderColor='#0af'; };
    zone.ondragleave = () => { zone.style.borderColor='#555'; };
    zone.ondrop = async e => {
      e.preventDefault(); zone.style.borderColor='#555';
      for (const item of e.dataTransfer.items) {
        if (item.kind === 'file') {
          const handle = await item.getAsFileSystemHandle();
          if (handle.kind === 'directory') return await readSRTsFromHandle(handle);
        }
      }
      return new Map();
    };
  }

  // ========================================================================
  // Live Transcription
  // ========================================================================

  async function startLiveTranscription() {
    const videoId = getVideoId();
    const url = `https://www.youtube.com/watch?v=${videoId}`;
    const payload = {
      source: url,
      model: state.model,
      device: state.modelConfig.device,
      compute_type: state.modelConfig.computeType,
      cpu_threads: state.modelConfig.cpuThreads,
      vad_filter: state.modelConfig.vadFilter,
      language: state.modelConfig.language,
      mpv_auto: false,
    };

    try {
      const res = await fetch(`${state.config.apiBase}/api/v1/live`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!data.task_id) throw new Error(data.detail || 'Failed to start live transcription');
      state.liveTaskId = data.task_id;
      connectLiveSSE(data.task_id);
      return data.task_id;
    } catch (e) {
      console.error('[ws] Live start failed:', e);
      showNotice('Live start failed: ' + e.message);
      throw e;
    }
  }

  function connectLiveSSE(taskId) {
    if (state.liveSSE) state.liveSSE.close();
    const url = `${state.config.apiBase}/api/v1/tasks/${taskId}/subtitles/stream`;
    state.liveSSE = new EventSource(url);
    state.liveSSE.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'segment' && data.segment) {
          // Append to cues
          const seg = data.segment;
          const cue = { start: seg.start, end: seg.end, text: seg.text };
          if (state.overlay) {
            state.overlay.cues.push(cue);
            state.overlay.cues.sort((a,b)=>a.start-b.start);
            state.overlay.injectTrack();
          }
        } else if (data.type === 'complete') {
          showNotice('Live transcription complete');
        }
      } catch (e) { console.error('[ws] SSE parse error:', e); }
    };
    state.liveSSE.onerror = () => {
      console.warn('[ws] SSE error, reconnecting...');
      setTimeout(() => connectLiveSSE(taskId), 3000);
    };
  }

  function connectLiveWS(taskId) {
    if (state.liveWS) state.liveWS.close();
    const ws = new WebSocket(`${state.config.apiBase.replace('http','ws')}/ws/${taskId}`);
    state.liveWS = ws;
    ws.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.type === 'segment' && data.segment) {
          const seg = data.segment;
          if (state.overlay) {
            state.overlay.cues.push({start:seg.start,end:seg.end,text:seg.text});
            state.overlay.cues.sort((a,b)=>a.start-b.start);
            state.overlay.injectTrack();
          }
        }
      } catch(e){console.error('[ws] WS parse error:',e);}
    };
    ws.onclose = () => setTimeout(() => connectLiveWS(taskId), 3000);
  }

  async function stopLiveTranscription() {
    if (state.liveSSE) { state.liveSSE.close(); state.liveSSE = null; }
    if (state.liveWS) { state.liveWS.close(); state.liveWS = null; }
    if (state.liveTaskId) {
      try { await fetch(`${state.config.apiBase}/api/v1/live/${state.liveTaskId}`, {method:'DELETE'}); }
      catch(e){console.warn('[ws] Failed to stop live:',e);}
      state.liveTaskId = null;
    }
    state.liveMode = false;
    showNotice('Live transcription stopped');
  }

  // ========================================================================
  // File handling
  // ========================================================================

  async function pickSRTDirectory() {
    if (!window.showDirectoryPicker) throw new Error('File System Access API unavailable');
    return window.showDirectoryPicker({ mode: 'read' });
  }

  async function readSRTsFromHandle(handle) {
    const map = new Map();
    for await (const [name, entry] of handle.entries()) {
      if (entry.kind === 'file' && name.toLowerCase().endsWith('.srt')) {
        const file = await entry.getFile();
        const text = await file.text();
        const videoId = extractVideoIdFromFilename(name);
        if (videoId && !map.has(videoId)) map.set(videoId, { path: name, content: text });
      }
    }
    return map;
  }

  function extractVideoIdFromFilename(name) {
    const m = name.match(/([a-zA-Z0-9_-]{11})/);
    return m ? m[1] : null;
  }

  async function loadFromDirectoryPicker() {
    try {
      const handle = await pickSRTDirectory();
      return await readSRTsFromHandle(handle);
    } catch (e) {
      if (e.name !== 'AbortError') console.warn('[ws] picker failed:', e);
      return new Map();
    }
  }

  function setupDragDrop() {
    const zone = document.createElement('div');
    zone.id = 'ws-dropzone';
    zone.style.cssText = `position:fixed;top:10px;right:10px;z-index:2147483647;padding:8px 12px;
      background:rgba(0,0,0,.8);color:#fff;border-radius:6px;font:12px monospace;
      cursor:pointer;border:2px dashed #555;transition:border-color .2s;`;
    zone.textContent = 'Drop SRT folder here';
    document.body.appendChild(zone);
    zone.ondragover=e=>{e.preventDefault();zone.style.borderColor='#0af';};
    zone.ondragleave=()=>{zone.style.borderColor='#555';};
    zone.ondrop=async e=>{e.preventDefault();zone.style.borderColor='#555';
      for(const item of e.dataTransfer.items){if(item.kind==='file'){
        const h=await item.getAsFileSystemHandle();if(h.kind==='directory')return await readSRTsFromHandle(h);
      }}
      return new Map();
    };
  }

  // ========================================================================
  // SubtitleOverlay (uses closure state)
  // ========================================================================

  class SubtitleOverlay {
    constructor(video) {
      this.video=video;this.cues=[];this.track=null;this.overlay=null;this.currentIdx=-1;
      this.syncOffset=0;this.enabled=true;this.cleanupFns=[];
      this.createOverlay();this.injectTrack();this.startSync();this.watchForReplacement();
    }
    createOverlay(){
      this.overlay=document.createElement('div');this.overlay.id='ws-overlay';
      this.overlay.style.cssText=`position:absolute;bottom:70px;left:50%;transform:translateX(-50%);
        pointer-events:none;z-index:2147483647;max-width:90%;text-align:center;
        font-size:18px;font-family:system-ui,sans-serif;color:#fff;
        background:rgba(0,0,0,.75);text-shadow:2px 2px 4px #000;
        padding:6px 12px;border-radius:6px;line-height:1.4;max-width:90%;
        white-space:pre-wrap;word-wrap:break-word;opacity:0;transition:opacity .2s;`;
      const c=this.video.parentElement;
      if(c){const s=getComputedStyle(c);if(s.position==='static')c.style.position='relative';c.appendChild(this.overlay);}
      else{this.overlay.style.position='fixed';this.overlay.style.bottom='90px';document.body.appendChild(this.overlay);}
    }
    injectTrack(){
      if(!this.cues.length)return;
      const vtt='WEBVTT\n\n'+this.cues.map((c,i)=>`${i+1}\n${fmt(c.start)} --> ${fmt(c.end)}\n${c.text}\n\n`).join('');
      const blob=new Blob([vtt],{type:'text/vtt'}),url=URL.createObjectURL(blob);
      if(this.track){URL.revokeObjectURL(this.track.src);this.track.remove();}
      this.track=document.createElement('track');
      this.track.kind='subtitles';this.track.label='whisper-subs';this.track.srclang='en';this.track.default=true;this.track.src=url;
      this.video.appendChild(this.track);
    }
    setCues(c){this.cues=c;this.injectTrack();}
    startSync(){
      const tick=()=>{if(!this.enabled||!this.video)return;
        const t=this.video.currentTime+this.syncOffset/1000;
        let idx=-1;for(let i=0;i<this.cues.length;i++){if(this.cues[i].start<=t&&t<=this.cues[i].end){idx=i;break;}}
        if(idx!==this.currentIdx){this.currentIdx=idx;this.render();}
        if(this.enabled)requestAnimationFrame(tick);
      };requestAnimationFrame(tick);
    }
    render(){if(!this.overlay)return;if(this.currentIdx>=0){this.overlay.textContent=this.cues[this.currentIdx].text;this.overlay.style.opacity='1';}else this.overlay.style.opacity='0';}
    setSyncOffset(ms){this.syncOffset=ms;}
    setEnabled(v){this.enabled=v;if(this.overlay)this.overlay.style.display=v?'block':'none';}
    destroy(){this.cleanupFns.forEach(f=>f());if(this.track){URL.revokeObjectURL(this.track.src);this.track.remove();}if(this.overlay)this.overlay.remove();this.enabled=false;}
    watchForReplacement(){
      this.observer=new MutationObserver(()=>{const v=getVideoElement();if(v&&v!==this.video){this.destroy();controller.init();}});
      this.observer.observe(document.body,{childList:true,subtree:true});
      this.cleanupFns.push(()=>this.observer?.disconnect());
    }
  }

  // ========================================================================
  // Main Controller
  // ========================================================================

  const controller = {
    overlay: null,
    video: null,
    srtMap: new Map(),
    liveMode: false,
    syncOffset: 0,
    stylesInjected: false,

    async init() {
      this.injectStyles();
      this.registerCommands();
      setupDragDrop();
      await this.waitAndAttach();
    },

    injectStyles() {
      if (this.stylesInjected) return;
      GM_addStyle(`
        #ws-overlay{animation:wsFade .2s ease}@keyframes wsFade{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%)}}
        #ws-dropzone:hover{border-color:#0af!important}
        #ws-panel{position:fixed;top:10px;right:10px;z-index:2147483647;background:rgba(0,0,0,.9);color:#fff;
          padding:12px;border-radius:8px;font:12px monospace;min-width:280px;max-height:80vh;overflow:auto}
        #ws-panel details{margin:8px 0}#ws-panel summary{cursor:pointer;font-weight:bold}
        #ws-panel label{display:block;margin:4px 0}#ws-panel select,#ws-panel input{width:100%;margin-top:2px;padding:4px;background:#222;color:#fff;border:1px solid #444;border-radius:4px}
        #ws-panel button{margin:4px 2px;padding:6px 10px;background:#444;border:none;color:#fff;border-radius:4px;cursor:pointer}
        #ws-panel button:hover{background:#666}#ws-panel button.primary{background:#007bff}
        #ws-panel .live{color:#0f0}#ws-panel .stopped{color:#f44}
        #ws-panel hr{border:none;border-top:1px solid #333;margin:8px 0}
      `);
      this.stylesInjected = true;
    },

    registerCommands() {
      GM_registerMenuCommand('whisper-subs: Pick SRT folder', () => this.pickFolder());
      GM_registerMenuCommand('whisper-subs: Toggle subtitles', () => this.toggle());
      GM_registerMenuCommand('whisper-subs: Sync +100ms', () => this.adjustSync(100));
      GM_registerMenuCommand('whisper-subs: Sync -100ms', () => this.adjustSync(-100));
      GM_registerMenuCommand('whisper-subs: Start live transcription', () => this.startLive());
      GM_registerMenuCommand('whisper-subs: Stop live transcription', () => this.stopLive());
      GM_registerMenuCommand('whisper-subs: Reload subtitles', () => this.reload());
      GM_registerMenuCommand('whisper-subs: Open settings', () => this.openSettings());
    },

    async pickFolder() {
      const map = await loadFromDirectoryPicker();
      if (map.size > 0) {
        this.srtMap = map;
        this.showNotice(`Loaded ${map.size} subtitle files`);
        this.reload();
      }
    },

    async loadCachedDirectory() {
      // FileSystemHandle can't be serialized; store path for re-pick
    },

    async waitAndAttach() {
      this.video = await waitForVideo();
      if (!this.video) return;
      this.overlay = new SubtitleOverlay(this.video);
      const vid = getVideoId();
      if (this.srtMap.has(vid)) {
        this.overlay.setCues(parseSRT(this.srtMap.get(vid).content));
      }
    },

    reload() {
      if (this.overlay) this.overlay.destroy();
      this.waitAndAttach();
    },

    toggle() {
      if (this.overlay) this.overlay.setEnabled(!this.overlay.enabled);
    },

    adjustSync(delta) {
      this.syncOffset += delta;
      if (this.overlay) this.overlay.setSyncOffset(this.syncOffset);
      this.showNotice(`Sync: ${this.syncOffset}ms`);
    },

    async startLive() {
      if (this.liveMode) return;
      try {
        this.liveMode = true;
        await startLiveTranscription();
        this.showNotice('Live transcription started');
        this.updatePanel();
      } catch (e) {
        this.liveMode = false;
        this.showNotice('Failed: ' + e.message);
      }
    },

    async stopLive() {
      if (!this.liveMode) return;
      await stopLiveTranscription();
      this.liveMode = false;
      this.showNotice('Live transcription stopped');
      this.updatePanel();
    },

    reload() {
      if (this.overlay) this.overlay.destroy();
      this.waitAndAttach();
    },

    openSettings() {
      const modal = document.createElement('div');
      modal.id = 'ws-panel';
      modal.innerHTML = this.buildSettingsHTML();
      document.body.appendChild(modal);
      this.bindSettingsEvents(modal);
    },

    buildSettingsHTML() {
      const m = this.modelConfig;
      let modelOpts = '';
      for (const [id, info] of Object.entries(MODEL_PRESETS)) {
        const badge = info.type === 'cloud' ? '☁' : info.type === 'adapter' ? '⚡' : '💻';
        modelOpts += `<option value="${id}" ${id===this.model?'selected':''}>${badge} ${id} (${info.size||''} ${info.note||''})</option>`;
      }
      return `
        <details open><summary>🎤 Model Selection</summary>
          <label>Model: <select id="ws-model">${modelOpts}</select></label>
          <label>Device: <select id="ws-device"><option value="cpu"${m.device==='cpu'?' selected':''}>CPU</option><option value="cuda"${m.device==='cuda'?' selected':''}>CUDA</option></select></label>
          <label>Compute: <select id="ws-compute"><option value="int8"${m.computeType==='int8'?' selected':''}>int8</option><option value="int16"${m.computeType==='int16'?' selected':''}>int16</option><option value="float16"${m.computeType==='float16'?' selected':''}>float16</option><option value="float32"${m.computeType==='float32'?' selected':''}>float32</option></select></label>
          <label>CPU Threads: <input type="number" id="ws-threads" value="${m.cpuThreads}" min="1" max="64" style="width:60px"></label>
          <label>Language: <input type="text" id="ws-lang" value="${m.language||'en'}" placeholder="en, auto, etc." style="width:100%"></label>
          <label><input type="checkbox" id="ws-vad"${m.vadFilter?' checked':''}> VAD Filter</label>
        </details>
        <details open><summary>📝 Subtitle Style</summary>
          <label>Font Size: <input type="number" id="ws-font" value="18" min="10" max="40" style="width:60px"> px</label>
          <label>Sync Offset: <input type="number" id="ws-sync" value="${this.syncOffset}" step="50" style="width:80px"> ms</label>
        </details>
        <details open><summary>🌐 API Server</summary>
          <label>Base URL: <input type="text" id="ws-api" value="${this.config.apiBase}" style="width:100%"></label>
        </details>
        <hr>
        <div style="display:flex;gap:4px">
          <button class="primary" id="ws-save">Save & Apply</button>
          <button id="ws-close">Close</button>
        </div>
      `;
    },

    bindSettingsEvents(modal) {
      modal.querySelector('#ws-save').onclick = () => {
        const m = modal;
        this.model = m.querySelector('#ws-model').value;
        this.modelConfig.device = m.querySelector('#ws-device').value;
        this.modelConfig.computeType = m.querySelector('#ws-compute').value;
        this.modelConfig.cpuThreads = parseInt(m.querySelector('#ws-threads').value) || 4;
        this.modelConfig.language = m.querySelector('#ws-lang').value || 'en';
        this.modelConfig.vadFilter = m.querySelector('#ws-vad').checked;
        this.config.apiBase = m.querySelector('#ws-api').value || 'http://localhost:8000';
        this.syncOffset = parseInt(m.querySelector('#ws-sync').value) || 0;
        const fontSize = parseInt(m.querySelector('#ws-font').value) || 18;
        if (this.overlay) this.overlay.fontSize = fontSize + 'px';
        if (this.overlay) this.overlay.setSyncOffset(this.syncOffset);
        saveConfig();
        this.showNotice('Settings saved');
      };
      m.querySelector('#ws-close').onclick = () => modal.remove();
      modal.onclick = e => { if (e.target === modal) modal.remove(); };
    },

    updatePanel() {
      // Panel auto-closes; could add a persistent panel if needed
    },

    showNotice(msg) {
      const n = document.createElement('div');
      n.textContent = msg;
      n.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
        background:rgba(0,0,0,.9);color:#0f0;padding:8px 16px;border-radius:6px;
        z-index:2147483647;font:12px monospace;animation:wsFade .2s,wsFadeOut .2s 2.5s forwards`;
      document.body.appendChild(n);
      setTimeout(() => n.remove(), 3000);
    },
  };

  // ========================================================================
  // Start
  // ========================================================================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => controller.init());
  } else {
    controller.init();
  }

  // Expose for debugging
  window.whisperSubs = controller;
})();
PYEOF

.venv/bin/python /tmp/tts_stt_test.py 2>&1 | head -100