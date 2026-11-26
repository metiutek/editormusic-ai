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
import Inspector from './Inspector.jsx'
import Mixer from './Mixer.jsx'
import PianoRoll from './PianoRoll.jsx'
import { Player } from './player.js'
import Versions from './Versions.jsx'
import { fmtPos, fmtTime } from './util.js'

const TABS = [['inspector', 'Inspector'], ['compose', 'Compose'], ['ai', 'AI'], ['mixer', 'Mixer'], ['chat', 'Assistant'], ['versions', 'Versions']]
const KEYS = ['C', 'C#', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

export default function App() {
  const [st, setSt] = useState(null)
  const [catalog, setCatalog] = useState({})
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [tab, setTab] = useState('compose')
  const [sel, setSel] = useState(null)
  const [rollClip, setRollClip] = useState(null)
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
  const player = useRef(null)
  if (!player.current) player.current = new Player()
  const project = st?.project
  const bpb = project ? (project.time_sig[0] * 4) / project.time_sig[1] : 4
  const spb = project ? 60 / project.bpm : 0.5
  const playheadBeat = pos / spb

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

  // stato del player -> React
  useEffect(() => {
    const p = player.current
    p.onState = () => { setPlaying(p.playing); setLoading(p.loading); setPos(p.position()) }
    let raf
    const tick = () => { if (p.playing) setPos(p.position()); raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
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

  const playPause = async () => {
    const p = player.current
    if (p.playing) { p.stop(); return }
    try { await p.play(st.revision, loopOn && loop ? Math.max(p.offset, loop[0] * spb) : p.offset) } catch (e) { setErr(e.message) }
  }
  const stop = () => { player.current.stop(true); setPos(0) }
  const seek = beat => { player.current.seek(beat * spb, st.revision); setPos(beat * spb) }

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
      else if (e.key === 'Home') seek(0)
      else if (e.key === 'l' || e.key === 'L') setLoopOn(x => !x)
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
    fd.append('bar', String(Math.floor(playheadBeat / bpb) + 1))
    setBusy('importing…')
    try { setSt(await api('/api/upload', { body: fd })) } catch (x) { setErr(x.message) }
    setBusy('')
  }

  const selectedTrack = useMemo(() => project?.tracks.find(t => t.id === (sel?.track || sel?.id)) || null, [project, sel])
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

  if (!st) return <div className="loading">{err || 'Loading medit…'}</div>

  return (
    <div className="app" onDragOver={e => e.preventDefault()} onDrop={onDrop}>
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
          <span className="clock" title="bar.beat · time">{fmtPos(playheadBeat, bpb)} <small>{fmtTime(pos)}</small></span>
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

      <div className="main">
        <div className="center">
          <div className="arr-bar">
            <label>Snap <select value={arrGrid} onChange={e => setArrGrid(Number(e.target.value))}>
              {[[bpb, 'bar'], [1, 'beat'], [0.5, '1/8'], [0.25, '1/16'], [0, 'off']].map(([v, n]) => <option key={n} value={v}>{n}</option>)}</select></label>
            <button className="icon-btn" title="Zoom out" onClick={() => setPpb(z => Math.max(4, z / 1.3))}>−</button>
            <button className="icon-btn" title="Zoom in" onClick={() => setPpb(z => Math.min(160, z * 1.3))}>+</button>
            <span className="hint">{project.bars} bars · {fmtTime(project.duration_s)} · double-click a MIDI track to add a clip, a clip to edit its notes</span>
          </div>
          <Arrange project={project} ppb={ppb} selection={sel} setSelection={s => { setSel(s); if (s) setTab(t => (t === 'compose' && s.kind !== 'track' ? 'inspector' : t)) }}
            run={run} playhead={playheadBeat} onSeek={seek} loop={loop} setLoop={l => { setLoopBeats(l); setLoopOn(true) }}
            grid={arrGrid} onOpenClip={id => setRollClip(id)}
            onAddTrack={kind => kind === 'bus' ? run('add_bus', { name: 'Reverb' }) : run('add_track', { kind, ...(kind === 'midi' ? { sound: 'piano' } : {}) })} />
          {rc && rc.track.kind === 'midi' && <PianoRoll project={project} clip={rc.clip} track={rc.track} run={run} player={player.current}
            grid={grid} setGrid={setGrid} playhead={playheadBeat} onClose={() => setRollClip(null)} />}
          {!project.tracks.length && <div className="empty-song">
            <Icon name="music" size={32} />
            <p>An empty song. Start from <b>Compose</b> (form, chords, drums, bass), drop an audio or MIDI file here,
              or ask the <b>Assistant</b>: <i>“a chill lo-fi beat in A minor, 8 bars”</i>.</p>
            <div className="row"><button onClick={() => setTab('compose')}>Compose</button><button onClick={() => setTab('chat')}>Assistant</button></div>
          </div>}
        </div>
        <div className="side">
          <div className="tabs">{TABS.map(([k, n]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}</button>)}</div>
          <div className="tab-body">
            {tab === 'inspector' && <Inspector project={project} selection={sel} catalog={catalog} run={run}
              playheadBar={playheadBeat / bpb + 1} onOpenClip={id => setRollClip(id)} analysis={analysis} onAnalyze={analizza} />}
            {tab === 'compose' && <Compose project={project} catalog={catalog} run={run} playheadBar={playheadBeat / bpb + 1} selectedTrack={selectedTrack} />}
            {tab === 'ai' && <AiPanel project={project} selection={sel} run={run} />}
            {tab === 'mixer' && <Mixer project={project} run={run} selection={sel} setSelection={setSel} analysis={analysis} onAnalyze={analizza} />}
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
        onPick={async paths => { setDialog(null); setBusy('importing…'); try { setSt(await api('/api/import', { body: { paths, bar: Math.floor(playheadBeat / bpb) + 1 } })) } catch (e) { setErr(e.message) } setBusy('') }} />}
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
