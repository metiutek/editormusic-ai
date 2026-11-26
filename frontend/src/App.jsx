// medit: arrangiamento al centro, piano roll sotto, pannelli a destra.
// La canzone vive nel server: la UI chiama le operazioni di Store e si
// aggiorna da sola quando a modificare e' l'agente (WebSocket).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, connectEvents, op } from './api.js'
import AiPanel from './AiPanel.jsx'
import Arrange from './Arrange.jsx'
import Chat from './Chat.jsx'
import Compose from './Compose.jsx'
import { Browse, Export, Modal, NewSong, Questions } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import Dock from './Dock.jsx'
import PianoRoll from './PianoRoll.jsx'
import { Player } from './player.js'
import { Recorder, encodeWav, trimStart } from './recorder.js'
import Splitter, { useSize } from './Splitter.jsx'
import Versions from './Versions.jsx'
import { Live } from './Widgets.jsx'
import { fmtPos, fmtTime } from './util.js'

// a destra l'agente; la traccia selezionata si lavora nel pannello in basso (Dock)
const TABS = [['chat', 'Assistant'], ['ai', 'AI tools'], ['compose', 'Compose'], ['versions', 'Versions']]
const KEYS = ['C', 'C#', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

export default function App() {
  const [st, setSt] = useState(null)
  const [catalog, setCatalog] = useState({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [tab, setTab] = useState('chat')
  const [sel, setSel] = useState(null)
  const [rollClip, setRollClip] = useState(null)
  // pannello in basso: si apre selezionando una traccia; view = track | master | mixer
  const [dock, setDock] = useState({ open: false, view: 'track' })
  const [fxIndex, setFxIndex] = useState(null)   // effetto aperto nel rack
  const [armed, setArmed] = useState(null)       // traccia audio armata per il Rec del trasporto
  const [countdown, setCountdown] = useState(0)
  const [recLane, setRecLane] = useState(null)    // {track, start (s)}: regione che cresce mentre si registra
  const [metroMenu, setMetroMenu] = useState(false)
  const [dialog, setDialog] = useState(null)
  const [question, setQuestion] = useState(null)
  const [llm, setLlm] = useState(null)
  const [ppb, setPpb] = useState(20)
  const [grid, setGrid] = useState(0.25)
  const [arrGrid, setArrGrid] = useState(1)
  const [pos, setPos] = useState(0)        // secondi
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loopOn, setLoopOn] = useState(false)
  const [loop, setLoopBeats] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [sideW, setSideW] = useSize('side', 360, 280, 900)
  const [rollH, setRollH] = useSize('roll', 300, 140, 900)
  const [dockH, setDockH] = useSize('dock', 380, 220, 900)
  const [headW, setHeadW] = useSize('head', 190, 120, 400)
  const player = useRef(null)
  if (!player.current) player.current = new Player()
  const project = st?.project
  const bpb = project ? (project.time_sig[0] * 4) / project.time_sig[1] : 4
  const spb = project ? 60 / project.bpm : 0.5
  const playheadBeat = pos / spb
  const spbRef = useRef(spb)
  spbRef.current = spb

  const ricarica = useCallback(async () => {
    try { setSt(await api('/api/project')) } catch (e) { setErr(e.message) }
  }, [])

  useEffect(() => {
    api('/api/state').then(s => {
      setSt(s)
      setCatalog({ effects: s.effects, sounds: s.sounds, chains: s.chains, instruments: s.instruments, theory: s.theory, home: s.home })
      setLlm(s.chat)
    }).catch(e => setErr(e.message))
    api('/api/domanda').then(r => r?.domanda && setQuestion(r.domanda)).catch(() => {})
    return connectEvents(ev => {
      if (ev.type === 'project') ricarica()
      if (ev.type === 'domande') setQuestion({ id: ev.id, domande: ev.domande })
      if (ev.type === 'domande_chiuse') setQuestion(q => (q && q.id === ev.id ? null : q))
    })
  }, [])

  // stato del player -> React. Il cursore e l'orologio si muovono da soli (Playhead, Live):
  // qui la posizione cambia solo a ogni beat, cosi' suonare non ridisegna tutta l'app.
  useEffect(() => {
    const p = player.current
    p.onState = () => { setPlaying(p.playing); setLoading(p.loading); setPos(p.position()) }
    let ultimo = -1
    return p.onFrame(t => {
      const b = Math.floor(t / (spbRef.current || 0.5))
      if (b !== ultimo) { ultimo = b; setPos(t) }
    })
  }, [])

  // la canzone cambia mentre suona: nuovo audio dallo stesso punto
  useEffect(() => { if (st?.revision) player.current.changed(st.revision).catch(e => setErr(e.message)) }, [st?.revision])

  useEffect(() => {
    player.current.setLoop(loopOn && loop ? [loop[0] * spb, loop[1] * spb] : null)
  }, [loopOn, loop?.[0], loop?.[1], spb])

  const run = useCallback(async (name, body = {}) => {
    const lenti = ['auto_master', 'balance_mix', 'add_audio', 'import_midi', 'compare_versions', 'generate_song',
      'generate_audio', 'separate_stems', 'audio_to_midi', 'convert_voice']
    if (lenti.includes(name)) setBusy(name.replace('_', ' ') + '…')
    try {
      const r = await op(name, body)
      setSt(s => ({ ...s, ...r }))
      setErr('')
      if (['save_sound', 'save_chain'].includes(name)) api('/api/presets').then(p => setCatalog(c => ({ ...c, ...p })))
      return r
    } catch (e) { setErr(e.message); return null } finally { if (lenti.includes(name)) setBusy('') }
  }, [])

  // ---- registrazione dal microfono ----
  const [rec, setRec] = useState('')          // '' | arming | rec | saving
  const recorder = useRef(null)
  const recInfo = useRef(null)
  const meterRef = useRef(null)
  const stRef = useRef(st)
  stRef.current = st
  const selTrackRef = useRef(null)

  const fermaRec = async () => {
    const p = player.current
    const r = recorder.current
    const info = recInfo.current
    if (!r || !info) return
    setRec('saving')
    setRecLane(null)
    const lat = r.latency()
    let res
    try { res = await r.stop(info.keepOpen) } catch (e) { setErr(e.message); setRec(''); return }
    p.stop()
    p.setLoop(info.loopPrima)
    // dove sta nella canzone il primo campione: ancora del player + latenza di andata e ritorno
    let song0 = info.anchor.song + (res.startTime - info.anchor.ctx) - lat
    let ch = res.channels
    if (song0 < 0) { ch = trimStart(ch, res.sampleRate, -song0); song0 = 0 }
    if (!ch.length || ch[0].length < res.sampleRate * 0.25) { setRec(''); setErr('Recording too short'); return }
    const fd = new FormData()
    fd.append('file', encodeWav(ch, res.sampleRate), 'take.wav')
    fd.append('bar', String(song0 / spbRef.current / info.bpb + 1))
    if (info.target) fd.append('track', info.target)
    setBusy('saving take…')
    try {
      const s = await api('/api/record', { body: fd })
      setSt(s)
      const tid = s.result?.track_id
      if (tid) setSel({ kind: 'track', id: tid, track: tid })
      setErr('')
    } catch (e) { setErr(e.message) }
    setBusy('')
    setRec('')
  }

  const registra = async trackId => {
    if (rec === 'rec') { fermaRec(); return }
    if (rec) return
    const p = player.current
    const r = getRecorder()
    const keepOpen = r.isOpen
    setRec('arming')
    try { await r.open() } catch (e) {
      setRec('')
      setErr(e.name === 'NotAllowedError' ? 'Microphone blocked: allow it in the browser (icon in the address bar)' : 'Microphone: ' + (e.message || e.name))
      return
    }
    r.onLevel = l => { if (meterRef.current) meterRef.current.style.transform = `scaleX(${(1 - Math.min(1, l)).toFixed(3)})` }
    let t = typeof trackId === 'string' ? trackId : armedRef.current || (selTrackRef.current?.kind === 'audio' ? selTrackRef.current.id : '')
    // nessuna traccia audio scelta: se ne crea una adesso, cosi' la registrazione si vede crescere li'
    if (!t) {
      const nr = await run('add_track', { kind: 'audio', name: 'Vocals', role: 'vocal' })
      t = nr?.result?.id || ''
      if (t) setSel({ kind: 'track', id: t, track: t })
    }
    const loopPrima = p.loop
    if (p.playing) p.stop()
    // count-in: battute di click prima di partire
    const bars = p.metro.countIn || 0
    if (bars > 0) {
      setRec('count')
      await p.countIn(bars, setCountdown)
    }
    p.loop = null                     // si registra in linea retta
    const at = p.offset
    const cur = stRef.current
    try { if (cur.project.tracks.some(x => x.clips.length)) await p.play(cur.revision, at) } catch { /* canzone vuota: si registra lo stesso */ }
    // canzone vuota (o audio non pronto): il tempo scorre lo stesso, cursore e metronomo avanzano
    if (!p.playing) await p.runFree(at)
    const anchor = { ctx: p.startedAt, song: p.offset }
    const pr = cur.project
    recInfo.current = { target: t, anchor, loopPrima, keepOpen, bpb: (pr.time_sig[0] * 4) / pr.time_sig[1] }
    r.start()
    setRecLane(t ? { track: t, start: at } : null)
    setRec('rec')
  }
  const getRecorder = () => recorder.current || (recorder.current = new Recorder(() => player.current._ctx()))
  const armedRef = useRef(null)
  armedRef.current = armed
  const registraRef = useRef(registra)
  registraRef.current = registra
  const onRecord = useCallback(id => registraRef.current(id), [])

  const playPause = async () => {
    const p = player.current
    if (rec === 'rec') { fermaRec(); return }
    if (rec === 'count') return
    if (p.playing) { p.stop(); return }
    try { await p.play(st.revision, loopOn && loop ? Math.max(p.offset, loop[0] * spb) : p.offset) } catch (e) { setErr(e.message) }
  }
  const stop = () => { player.current.stop(true); setPos(0) }
  const revRef = useRef(null)
  revRef.current = st?.revision
  const seek = useCallback(beat => { player.current.seek(beat * spbRef.current, revRef.current); setPos(beat * spbRef.current) }, [])
  const nowBar = () => Math.floor(player.current.position() / spb / bpb) + 1

  const analizza = async () => {
    setBusy('measuring…')
    try { setAnalysis(await api('/api/analyze')) } catch (e) { setErr(e.message) }
    setBusy('')
  }

  // scorciatoie
  useEffect(() => {
    const key = e => {
      if (e.target.closest('input, textarea, select') || dialog || question) return
      const mod = e.ctrlKey || e.metaKey
      if (e.code === 'Space') { e.preventDefault(); playPause() }
      else if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); run(e.shiftKey ? 'redo' : 'undo') }
      else if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); run('redo') }
      else if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); salva() }
      else if (mod && e.key.toLowerCase() === 'd' && sel?.kind === 'clip') { e.preventDefault(); run('duplicate_clip', { clip: sel.id }) }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && sel?.kind === 'clip' && !rollClip) { e.preventDefault(); run('remove_clip', { clip: sel.id }); setSel(null) }
      else if (e.key === 'Delete' && sel?.kind === 'track' && !rollClip) { e.preventDefault(); run('remove_track', { track: sel.id }); setSel(null) }
      else if (e.key === 'Escape') { if (rollClip) setRollClip(null); else if (dock.open) setDock(d => ({ ...d, open: false })); else setSel(null) }
      else if (e.key === 'Home') seek(0)
      else if (e.key === 'l' || e.key === 'L') setLoopOn(x => !x)
      else if ((e.key === 'r' || e.key === 'R') && !mod) { e.preventDefault(); registra() }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })

  const salva = async () => {
    if (!st?.path) { setDialog('saveas'); return }
    try { setSt(await api('/api/project/save', { body: {} })) } catch (e) { setErr(e.message) }
  }

  // file trascinati sulla finestra: audio e MIDI alla battuta del cursore
  const onDrop = async e => {
    e.preventDefault()
    if (!e.dataTransfer.files.length) return
    const fd = new FormData()
    for (const f of e.dataTransfer.files) fd.append('files', f)
    fd.append('bar', String(nowBar()))
    setBusy('importing…')
    try { setSt(await api('/api/upload', { body: fd })) } catch (x) { setErr(x.message) }
    setBusy('')
  }

  const selectedTrack = useMemo(() => project?.tracks.find(t => t.id === (sel?.track || sel?.id)) || null, [project, sel])
  selTrackRef.current = selectedTrack
  const rc = useMemo(() => {
    if (!rollClip || !project) return null
    for (const t of project.tracks) {
      const c = t.clips.find(c => c.id === rollClip)
      if (c) return { clip: c, track: t }
    }
    return null
  }, [rollClip, project])
  useEffect(() => { if (rollClip && project && !rc) setRollClip(null) }, [rc])

  const refsSel = []
  if (sel?.kind === 'clip') {
    const c = rc?.clip?.id === sel.id ? rc.clip : project?.tracks.flatMap(t => t.clips).find(c => c.id === sel.id)
    if (c) refsSel.push({ type: 'clip', id: c.id, name: c.name })
  }
  if (selectedTrack) refsSel.push({ type: 'track', id: selectedTrack.id, name: selectedTrack.name })
  if (loop) refsSel.push({ type: 'bars', from: loop[0] / bpb + 1, to: loop[1] / bpb, name: `${loop[0] / bpb + 1}-${loop[1] / bpb}` })

  // selezionare una traccia, una clip o una sezione apre il pannello in basso
  const selectArr = useCallback(s => {
    setSel(prev => {
      const tr = x => x && (x.kind === 'track' ? x.id : x.track)
      if (tr(prev) !== tr(s)) setFxIndex(null)
      return s
    })
    if (s) setDock({ open: true, view: 'track' })
  }, [])
  const setLoopArr = useCallback(l => { setLoopBeats(l); setLoopOn(true) }, [])
  const addTrack = useCallback(kind => kind === 'bus' ? run('add_bus', { name: 'Reverb' })
    : run('add_track', { kind, ...(kind === 'midi' ? { sound: 'piano' } : {}) }), [run])
  const closeRoll = useCallback(() => setRollClip(null), [])
  // un pannello in basso alla volta: effetto o piano roll
  // dal mixer: un insert apre il rack di quella traccia (o del master) su quell'effetto
  const openFx = useCallback((target, index) => {
    if (target === 'master') setDock({ open: true, view: 'master' })
    else { setSel({ kind: 'track', id: target, track: target }); setDock({ open: true, view: 'track' }) }
    setFxIndex(index)
    setRollClip(null)
  }, [])
  const openRoll = useCallback(id => setRollClip(id), [])
  useEffect(() => { if (project) player.current.setTempo(60 / project.bpm, bpb) }, [project?.bpm, bpb])
  // fine della canzone (con la coda) per la riproduzione a pezzi; errori di render in barra
  useEffect(() => { if (project) player.current.setSongEnd(project.duration_s + 2) }, [project?.duration_s])
  useEffect(() => { player.current.onError = e => setErr('Playback: ' + e.message) }, [])
  const fit = () => {
    const el = document.querySelector('.arrange')
    if (!el || !project) return
    const beats = Math.max(4, project.bars) * bpb
    setPpb(Math.max(2, Math.min(200, (el.clientWidth - headW - 30) / beats)))
    el.scrollLeft = 0
  }

  if (!st) return <div className="loading">{err || 'Loading medit…'}</div>

  return (
    <div className={'app' + (rec === 'rec' ? ' recording' : '')} onDragOver={e => e.preventDefault()} onDrop={onDrop}>
      <div className="topbar">
        <img className="logo" src="./logo.svg" alt="" /><b className="brand">medit</b>
        <span className="docname" title={st.path || 'not saved'}>{project?.name}{st.path ? '' : ' •'}</span>
        <button onClick={() => setDialog('new')}>New</button>
        <button onClick={() => setDialog('open')}>Open</button>
        <button onClick={salva} title="Ctrl+S">Save</button>
        <span className="sep" />
        <button className="icon-btn" title="Undo (Ctrl+Z)" disabled={!st.history?.undo} onClick={() => run('undo')}><Icon name="undo" /></button>
        <button className="icon-btn" title="Redo (Ctrl+Shift+Z)" disabled={!st.history?.redo} onClick={() => run('redo')}><Icon name="redo" /></button>
        <span className="sep" />
        <div className="transport">
          <button className="icon-btn" title="To the start (Home)" onClick={stop}><Icon name="rewind" /></button>
          <button className={'icon-btn play' + (playing ? ' on' : '')} title="Play / pause (Space)" onClick={playPause}>
            <Icon name={playing ? 'pause' : 'play'} /></button>
          <button className={'icon-btn' + (loopOn ? ' on' : '')} title="Loop (L): drag on the ruler to set the region" onClick={() => setLoopOn(!loopOn)}><Icon name="loop" /></button>
          <button className={'icon-btn rec-btn' + (rec ? ' ' + rec : '')} disabled={rec === 'arming' || rec === 'saving'}
            title={rec === 'rec' ? 'Stop recording (R or Space)' : `Record from the microphone (R) · from the playhead, onto ${selectedTrack?.kind === 'audio' ? '"' + selectedTrack.name + '"' : 'a new "Vocals" track'} · use headphones`}
            onClick={registra}><Icon name="rec" /></button>
          {rec === 'rec' && <span className="rec-meter" title="Input level"><i ref={meterRef} /></span>}
          {rec === 'count' && <span className="count-in">{countdown}</span>}
          <div className="metro-wrap">
            <button className={'icon-btn' + (player.current.metro.on ? ' on' : '')} title="Metronome (plays while playing and recording, never in the mix)"
              onClick={() => player.current.setMetro({ on: !player.current.metro.on })}><Icon name="metronome" /></button>
            <button className="icon-btn caret" title="Metronome settings and count-in" onClick={() => setMetroMenu(!metroMenu)}><Icon name="down" size={11} /></button>
            {metroMenu && <MetroMenu player={player.current} onClose={() => setMetroMenu(false)} />}
          </div>
          <span className="clock" title="bar.beat · time"><Live player={player.current} format={t => `${fmtPos(t / spb, bpb)}  ${fmtTime(t)}`} /></span>
          {loading && <span className="hint">rendering…</span>}
        </div>
        <span className="sep" />
        <label className="mini">BPM <input type="number" min={20} max={400} defaultValue={project.bpm} key={'b' + project.bpm}
          onBlur={e => Number(e.target.value) !== project.bpm && run('set_song', { bpm: Number(e.target.value) })}
          onKeyDown={e => e.key === 'Enter' && e.target.blur()} /></label>
        <label className="mini">Key <select value={project.key} onChange={e => run('set_song', { key: e.target.value, mode: project.mode })}>
          {[...new Set([...KEYS, project.key])].map(k => <option key={k}>{k}</option>)}</select>
          <select value={project.mode} onChange={e => run('set_song', { mode: e.target.value })}>
            {(catalog.theory?.modes || ['major', 'minor']).map(m => <option key={m}>{m}</option>)}</select></label>
        <label className="mini">{project.time_sig.join('/')}</label>
        <span className="grow" />
        {busy && <span className="busy">{busy}</span>}
        <button onClick={() => setDialog('import')}><Icon name="folder" size={14} /> Import</button>
        <button className="primary" onClick={() => setDialog('export')}><Icon name="download" size={14} /> Export</button>
      </div>
      {err && <div className="errbar" onClick={() => setErr('')}>{err} <small>(click to close)</small></div>}

      <div className="main" style={{ gridTemplateColumns: `1fr 6px ${sideW}px` }}>
        <div className="center">
          <div className="arr-bar">
            <label>Snap <select value={arrGrid} onChange={e => setArrGrid(Number(e.target.value))}>
              {[[bpb, 'bar'], [1, 'beat'], [0.5, '1/8'], [0.25, '1/16'], [0, 'off']].map(([v, n]) => <option key={n} value={v}>{n}</option>)}</select></label>
            <button className="icon-btn" title="Zoom out (Ctrl+wheel)" onClick={() => setPpb(z => Math.max(2, z / 1.3))}>−</button>
            <button className="icon-btn" title="Zoom in (Ctrl+wheel)" onClick={() => setPpb(z => Math.min(200, z * 1.3))}>+</button>
            <button className="icon-btn" title="Fit the whole song" onClick={fit}><Icon name="expand" size={14} /></button>
            <button className={dock.open && dock.view === 'mixer' ? 'on' : ''} title="Mixer: all channels in the bottom panel"
              onClick={() => setDock(d => (d.open && d.view === 'mixer' ? { ...d, open: false } : { open: true, view: 'mixer' }))}><Icon name="sliders" size={13} /> Mixer</button>
            <button className={dock.open && dock.view === 'master' ? 'on' : ''} title="Master effects and mastering"
              onClick={() => setDock(d => (d.open && d.view === 'master' ? { ...d, open: false } : { open: true, view: 'master' }))}>Master</button>
            <span className="hint ellipsis">{Math.round(project.bars * 100) / 100} bars · {fmtTime(project.duration_s)} · double-click a name to rename · right-click for more · Ctrl+wheel to zoom</span>
          </div>
          <Arrange project={project} ppb={ppb} setPpb={setPpb} selection={sel} setSelection={selectArr}
            run={run} player={player.current} spb={spb} onSeek={seek} loop={loop} setLoop={setLoopArr}
            grid={arrGrid} onOpenClip={openRoll} head={headW} onHead={setHeadW} onAddTrack={addTrack} onRecord={onRecord}
            armed={armed} onArm={id => setArmed(a => (a === id ? null : id))} recLane={recLane} />
          {rc && rc.track.kind === 'midi' && <>
            <Splitter dir="y" sign={-1} value={rollH} onChange={setRollH} onReset={() => setRollH(300)}
              title="Drag to resize the piano roll · double-click to reset" />
            <PianoRoll project={project} clip={rc.clip} track={rc.track} run={run} player={player.current} height={rollH}
              grid={grid} setGrid={setGrid} spb={spb} onClose={closeRoll} /></>}
          {dock.open && !(rc && rc.track.kind === 'midi') && <>
            <Splitter dir="y" sign={-1} value={dockH} onChange={setDockH} onReset={() => setDockH(380)}
              title="Drag to resize the track panel · double-click to reset" />
            <Dock project={project} sel={sel} view={dock.view} setView={v => setDock({ open: true, view: v })}
              fxIndex={fxIndex} setFxIndex={setFxIndex} catalog={catalog} run={run} player={player.current} revision={st.revision}
              height={dockH} recorder={getRecorder} rec={rec} countdown={countdown} armed={armed} onArm={setArmed} onRecord={onRecord}
              analysis={analysis} onAnalyze={analizza} onOpenClip={openRoll} playheadBar={playheadBeat / bpb + 1}
              setSelection={selectArr} onOpenFx={openFx} onClose={() => setDock(d => ({ ...d, open: false }))} /></>}
          {!project.tracks.length && <div className="empty-song">
            <Icon name="music" size={32} />
            <p>An empty song. Start from <b>Compose</b> (form, chords, drums, bass), drop an audio or MIDI file here,
              or ask the <b>Assistant</b>: <i>“a chill lo-fi beat in A minor, 8 bars”</i>.</p>
            <div className="row"><button onClick={() => setTab('compose')}>Compose</button><button onClick={() => setTab('chat')}>Assistant</button></div>
          </div>}
        </div>
        <Splitter dir="x" sign={-1} value={sideW} onChange={setSideW} onReset={() => setSideW(360)}
          title="Drag to resize the side panel · double-click to reset" />
        <div className="side">
          <div className="tabs">{TABS.map(([k, n]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}</button>)}</div>
          <div className="tab-body">
            {tab === 'compose' && <Compose project={project} catalog={catalog} run={run} playheadBar={playheadBeat / bpb + 1} selectedTrack={selectedTrack} />}
            {tab === 'ai' && <AiPanel project={project} selection={sel} run={run} />}
            {tab === 'chat' && <Chat llm={llm} setLlm={setLlm} refsSel={refsSel} docPath={st.path} />}
            {tab === 'versions' && <Versions revision={st.revision} run={run} />}
          </div>
        </div>
      </div>

      {dialog === 'new' && <NewSong modes={catalog.theory?.modes} home={catalog.home} onClose={() => setDialog(null)}
        onCreate={async body => { try { setSt(await api('/api/project/create', { body })); setSel(null); setRollClip(null); stop(); setDialog(null) } catch (e) { setErr(e.message) } }} />}
      {dialog === 'open' && <Browse mode="open" home={catalog.home} onClose={() => setDialog(null)}
        onPick={async ([p]) => { setBusy('opening…'); try { setSt(await api('/api/project/open', { body: { path: p } })); setSel(null); setRollClip(null); stop(); setDialog(null) } catch (e) { setErr(e.message) } setBusy('') }} />}
      {dialog === 'import' && <Browse mode="import" home={catalog.home} onClose={() => setDialog(null)}
        onPick={async paths => { setDialog(null); setBusy('importing…'); try { setSt(await api('/api/import', { body: { paths, bar: nowBar() } })) } catch (e) { setErr(e.message) } setBusy('') }} />}
      {dialog === 'export' && <Export project={project} home={catalog.home} path={st.path} onClose={() => setDialog(null)}
        onDone={r => { setDialog({ done: r }) }} />}
      {dialog?.done && <Modal title="Exported" onClose={() => setDialog(null)}>
        <p>{dialog.done.path || dialog.done.folder}</p>
        {dialog.done.lufs !== undefined && <p className="hint">{dialog.done.duration_s} s · {dialog.done.lufs} LUFS · peak {dialog.done.peak_db} dB</p>}
        {dialog.done.stems && <p className="hint">{dialog.done.stems.length} stems</p>}
        <div className="modal-foot"><button className="primary" onClick={() => setDialog(null)}>OK</button></div>
      </Modal>}
      {dialog === 'saveas' && <SaveAs home={catalog.home} name={project.name} onClose={() => setDialog(null)}
        onSave={async path => { try { setSt(await api('/api/project/save', { body: { path } })); setDialog(null) } catch (e) { setErr(e.message) } }} />}
      {question && <Questions q={question} onAnswer={async risposte => {
        const id = question.id
        setQuestion(null)
        try { await api(`/api/domanda/${id}`, { body: { risposte } }) } catch { /* scaduta */ }
      }} />}
    </div>
  )
}

// metronomo: suono, volume, count-in (come nei DAW: menu accanto al pulsante)
function MetroMenu({ player, onClose }) {
  const ref = useRef(null)
  const [, bump] = useState(0)
  const m = player.metro
  const set = ch => { player.setMetro(ch); bump(x => x + 1) }
  useEffect(() => {
    const fuori = e => { if (!ref.current?.contains(e.target) && !e.target.closest('.metro-wrap')) onClose() }
    window.addEventListener('pointerdown', fuori, true)
    return () => window.removeEventListener('pointerdown', fuori, true)
  }, [onClose])
  return (
    <div className="popover metro-menu" ref={ref}>
      <label className="check"><input type="checkbox" checked={m.on} onChange={e => set({ on: e.target.checked })} /> Metronome on</label>
      <div className="mm-sec">Sound</div>
      <div className="seg">{['click', 'tick', 'hihat', 'clave'].map(k => <button key={k} className={m.sound === k ? 'on' : ''}
        onClick={() => { set({ sound: k }); const c = player._ctx(); c.resume(); player.click(c.currentTime + 0.02, true) }}>{k}</button>)}</div>
      <div className="mm-sec">Volume</div>
      <input type="range" min={0} max={1} step={0.05} value={m.volume} onChange={e => set({ volume: Number(e.target.value) })} />
      <div className="mm-sec">Count-in before recording</div>
      <div className="seg">{[[0, 'Off'], [1, '1 bar'], [2, '2 bars']].map(([v, n]) => <button key={v} className={m.countIn === v ? 'on' : ''}
        onClick={() => set({ countIn: v })}>{n}</button>)}</div>
    </div>
  )
}

function SaveAs({ home, name, onSave, onClose }) {
  const [p, setP] = useState(`${home}/${name || 'song'}.json`)
  return (
    <Modal title="Save song as" onClose={onClose}>
      <label className="field wide"><span>File (.json)</span><input value={p} onChange={e => setP(e.target.value)} /></label>
      <p className="hint">The song stays a small JSON file; generated audio goes in a folder next to it.</p>
      <div className="modal-foot"><button onClick={onClose}>Cancel</button><button className="primary" onClick={() => onSave(p)}>Save</button></div>
    </Modal>
  )
}
