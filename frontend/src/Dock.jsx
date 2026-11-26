// Pannello traccia in basso: si apre quando si seleziona una traccia (o una sua clip).
// Il flusso e' quello dei DAW da browser: preset in testa con le manopole rapide,
// riga d'ingresso (microfono, meter, monitoraggio, calibrazione, registra) per le tracce
// audio, rack di effetti a schede e sotto l'editor completo dell'effetto scelto.
// La colonna di destra resta all'Assistant; tutto il resto della traccia sta qui.
import { useEffect, useMemo, useRef, useState } from 'react'
import FxPanel, { Knob } from './FxPanel.jsx'
import Icon from './Icons.jsx'
import { SectionInspector } from './Inspector.jsx'
import { ClipPanel, MasterKnobs, SoundPanel, TrackPanel } from './Panels.jsx'
import Mixer from './Mixer.jsx'
import { Recorder } from './recorder.js'
import { titleCase } from './util.js'

// ---------------------------------------------------------------- nomi e colori

export const FX_NAMES = {
  eq: 'Parametric EQ', graphic_eq: 'Graphic EQ', autotune: 'Auto-Tune', deesser: 'De-esser', lofi: 'Lo-fi',
  pitch_shift: 'Pitch shift', stereo_width: 'Stereo width', filter_lfo: 'Filter LFO', ring_mod: 'Ring mod',
  multiband: 'Multiband comp', transient: 'Transient shaper', lowpass: 'Low-pass', highpass: 'High-pass', bandpass: 'Band-pass',
}
export const fxName = t => FX_NAMES[t] || titleCase(t)
const GROUP_COLOR = { pitch: '#c58cff', tone: '#4fc3f7', dynamics: '#ffb347', space: '#4fd18b', modulation: '#ff6b9a', color: '#ff7a59', utility: '#9497aa' }
const GROUPS = [['pitch', 'Pitch'], ['tone', 'EQ & filters'], ['dynamics', 'Dynamics'], ['space', 'Space'], ['modulation', 'Modulation'], ['color', 'Saturation'], ['utility', 'Utility']]
// le due manopole che contano di piu', sulla scheda del rack
const MACRO = {
  eq: ['mid_gain', 'high_gain'], graphic_eq: ['g125', 'g4k'], compressor: ['threshold_db', 'ratio'], limiter: ['gain_db', 'ceiling_db'],
  gate: ['threshold_db', 'range_db'], deesser: ['threshold_db', 'freq'], reverb: ['decay', 'mix'], delay: ['feedback', 'mix'],
  chorus: ['rate', 'mix'], flanger: ['rate', 'mix'], phaser: ['rate', 'mix'], distortion: ['drive', 'mix'], bitcrusher: ['bits', 'mix'],
  lofi: ['wow', 'mix'], autotune: ['speed_ms', 'amount'], pitch_shift: ['semitones', 'mix'], doubler: ['width', 'mix'],
  exciter: ['drive', 'amount'], stereo_width: ['width', 'bass_mono'], tremolo: ['depth', 'rate_beats'], autopan: ['depth', 'rate_beats'],
  pump: ['depth', 'rate_beats'], transient: ['attack', 'sustain'], multiband: ['ratio', 'mix'], lowpass: ['cutoff', 'q'],
  highpass: ['cutoff', 'q'], bandpass: ['cutoff', 'q'], filter_lfo: ['rate', 'mix'], gain: ['db', 'pan'], ring_mod: ['freq', 'mix'],
  vibrato: ['rate', 'depth'],
}
const KNOB_LABEL = { threshold_db: 'Thresh', ratio: 'Ratio', mid_gain: 'Bell', high_gain: 'High', g125: '125', g4k: '4k', gain_db: 'Gain',
  ceiling_db: 'Ceiling', range_db: 'Range', speed_ms: 'Speed', semitones: 'Semi', bass_mono: 'Bass mono', rate_beats: 'Rate', db: 'Gain' }
const knobLabel = k => KNOB_LABEL[k] || titleCase(k.replace(/_(ms|db|hz)$/, ''))

export const FAMILIES = [['voice clean', 'Voice · Clean'], ['voice rap', 'Voice · Rap'], ['voice experimental', 'Voice · Experimental'],
  ['voice spaces', 'Voice · Spaces'], ['instrument', 'Instruments'], ['bus', 'Bus'], ['master', 'Master'], ['mine', 'My presets']]

// ---------------------------------------------------------------- piccoli pezzi

function usePopover(open, setOpen) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const fuori = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    window.addEventListener('pointerdown', fuori, true)
    window.addEventListener('keydown', esc, true)
    return () => { window.removeEventListener('pointerdown', fuori, true); window.removeEventListener('keydown', esc, true) }
  }, [open, setOpen])
  return ref
}

// manopola che mostra il valore mentre si gira e lo manda al rilascio
function LiveKnob({ value, onCommit, ...rest }) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  return <Knob {...rest} value={v} onChange={setV} onCommit={x => { setV(x); if (x !== value) onCommit(x) }} />
}

// ---------------------------------------------------------------- preset

function familyFor(track, target) {
  if (target === 'master') return 'master'
  if (track?.kind === 'bus') return 'bus'
  if (track?.kind === 'audio' || track?.role === 'vocal') return 'voice clean'
  return 'instrument'
}

// la catena attuale e' esattamente un preset? (stessi effetti nello stesso ordine)
function currentPreset(chains, effects) {
  const tipi = effects.map(e => e.type).join('|')
  if (!tipi) return null
  // stessi effetti e, per ognuno, i valori che il preset imposta (se li hai cambiati diventa "Custom")
  const uguale = (v, w) => (typeof v === 'number' && typeof w === 'number' ? Math.abs(v - w) < 1e-6 : v === w)
  return chains.find(c => c.effects.join('|') === tipi &&
    (c.params || []).every((p, i) => Object.entries(p || {}).every(([k, v]) => uguale(effects[i].params?.[k], v)))) || null
}

function PresetBar({ target, track, effects, chains, run }) {
  const [open, setOpen] = useState(false)
  const fam0 = familyFor(track, target)
  const cur = currentPreset(chains, effects)
  const famNow = cur?.category || fam0
  const [fam, setFam] = useState(famNow)
  useEffect(() => { setFam(famNow) }, [famNow, open])
  const ref = usePopover(open, setOpen)
  // frecce: preset precedente/successivo della stessa famiglia
  const lista = chains.filter(c => c.category === famNow)
  const passo = d => {
    if (!lista.length) return
    const i = cur ? lista.findIndex(c => c.name === cur.name) : -1
    const n = lista[(i + d + lista.length) % lista.length]
    run('apply_chain', { target, name: n.name, replace: true })
  }
  return (
    <div className="preset-bar" ref={ref}>
      <button className="icon-btn" title="Previous preset" onClick={() => passo(-1)}>‹</button>
      <button className="preset-name" onClick={() => setOpen(!open)} title="Browse presets">
        <span className="grow ellipsis">{cur ? titleCase(cur.name) : effects.length ? 'Custom chain' : 'No preset'}</span>
        <Icon name="down" size={11} />
      </button>
      <button className="icon-btn" title="Next preset" onClick={() => passo(1)}>›</button>
      <button className="link" title="Save this chain as a preset, for every song"
        disabled={!effects.length} onClick={() => { const n = prompt('Preset name'); if (n) run('save_chain', { name: n, target }) }}>Save preset…</button>
      {open && <div className="popover preset-browser">
        <div className="pb-fams">
          {FAMILIES.map(([k, n]) => {
            const c = chains.filter(x => x.category === k).length
            return c ? <button key={k} className={fam === k ? 'on' : ''} onClick={() => setFam(k)}>{n}<small>{c}</small></button> : null
          })}
        </div>
        <div className="pb-list">
          {chains.filter(c => c.category === fam).map(c => (
            <button key={c.name} className={'pb-item' + (cur?.name === c.name ? ' on' : '')}
              onClick={() => { run('apply_chain', { target, name: c.name, replace: true }); setOpen(false) }}>
              <b>{titleCase(c.name)}{c.user ? ' ★' : ''}</b>
              <span>{c.desc}</span>
              <small>{c.effects.map(fxName).join(' → ')}</small>
            </button>))}
          <p className="hint">A preset replaces the whole chain (one undo).</p>
        </div>
      </div>}
    </div>
  )
}

// Reverb, Pan, Volume: le tre manopole che si toccano sempre
function QuickKnobs({ target, track, project, effects, run }) {
  const iRev = effects.map(e => e.type).lastIndexOf('reverb')
  const rev = iRev >= 0 ? (effects[iRev].params?.mix ?? 0.25) : 0
  const vol = track ? track.volume_db : project.master.volume_db
  return (
    <div className="quick-knobs">
      <LiveKnob label="Reverb" size={38} value={rev} p={{ min: 0, max: 1, default: 0, desc: 'reverb dry/wet (adds a reverb if missing)' }}
        onCommit={v => iRev >= 0 ? run('update_effect', { target, index: iRev, params: { mix: v } })
          : v > 0 && run('add_effect', { target, type: 'reverb', params: { mix: v } })} />
      {track && <LiveKnob label="Pan" size={38} value={track.pan || 0} p={{ min: -1, max: 1, default: 0, desc: 'pan' }}
        onCommit={v => run('set_track', { track: track.id, pan: v })} />}
      <LiveKnob label="Volume" size={38} value={vol} p={{ min: -60, max: 12, default: 0, unit: 'dB', desc: 'volume' }}
        onCommit={v => track ? run('set_track', { track: track.id, volume_db: v }) : run('set_master', { volume_db: v })} />
    </div>
  )
}

// ---------------------------------------------------------------- rack

function FxCard({ e, i, n, spec, sel, target, run, onSelect }) {
  const macro = (MACRO[e.type] || Object.keys(spec?.params || {}).filter(k => spec.params[k].type === 'float')).slice(0, 2)
  const params = { ...Object.fromEntries(Object.entries(spec?.params || {}).map(([k, p]) => [k, p.default])), ...(e.params || {}) }
  const stop = ev => ev.stopPropagation()
  return (
    <div className={'fx-card' + (sel ? ' sel' : '') + (e.enabled === false ? ' off' : '')} style={{ '--g': GROUP_COLOR[spec?.group] || '#9497aa' }}
      onClick={() => onSelect(i)} title={spec?.desc}>
      <div className="fc-head">
        <button className={'fc-power' + (e.enabled !== false ? ' on' : '')} title={e.enabled === false ? 'Turn on' : 'Bypass'}
          onClick={ev => { stop(ev); run('update_effect', { target, index: i, enabled: e.enabled === false }) }}><Icon name="power" size={11} /></button>
        <b className="grow ellipsis">{fxName(e.type)}</b>
        <button className="icon-btn fc-x" title="Remove" onClick={ev => { stop(ev); run('remove_effect', { target, index: i }) }}>✕</button>
      </div>
      <div className="fc-knobs" onClick={stop}>
        {macro.filter(k => spec?.params?.[k]).map(k => <LiveKnob key={k} size={34} label={knobLabel(k)} value={params[k]} p={spec.params[k]}
          color={GROUP_COLOR[spec.group]} onCommit={v => run('update_effect', { target, index: i, params: { [k]: v } })} />)}
      </div>
      <div className="fc-move" onClick={stop}>
        <button className="icon-btn" disabled={i === 0} title="Move earlier in the chain" onClick={() => { run('move_effect', { target, index: i, to: i - 1 }); onSelect(i - 1) }}>‹</button>
        <span className="hint">{i + 1}</span>
        <button className="icon-btn" disabled={i === n - 1} title="Move later in the chain" onClick={() => { run('move_effect', { target, index: i, to: i + 1 }); onSelect(i + 1) }}>›</button>
      </div>
    </div>
  )
}

function recenti() { try { return JSON.parse(localStorage.getItem('medit.fx.recent') || '[]') } catch { return [] } }

function FxLibrary({ catalog, onPick, onClose }) {
  const [q, setQ] = useState('')
  const [g, setG] = useState('all')
  const rec = recenti()
  const ref = usePopover(true, onClose)
  const lista = (catalog || []).filter(e => (g === 'all' || (g === 'recent' ? rec.includes(e.name) : e.group === g)) &&
    (!q || (e.name + ' ' + fxName(e.name) + ' ' + e.desc).toLowerCase().includes(q.toLowerCase())))
  return (
    <div className="popover fx-library" ref={ref}>
      <input autoFocus placeholder="Search: reverb, EQ, tune, delay…" value={q} onChange={e => setQ(e.target.value)}
        onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter' && lista[0]) onPick(lista[0].name) }} />
      <div className="chips">
        {[['all', 'All'], ...(rec.length ? [['recent', 'Recent']] : []), ...GROUPS].map(([k, n]) =>
          <button key={k} className={g === k ? 'on' : ''} onClick={() => setG(k)}>{n}</button>)}
      </div>
      <div className="fl-list">
        {lista.map(e => <button key={e.name} className="fl-item" style={{ '--g': GROUP_COLOR[e.group] }} onClick={() => onPick(e.name)}>
          <i /><b>{fxName(e.name)}</b><span>{e.desc}</span></button>)}
        {!lista.length && <p className="hint">Nothing found.</p>}
      </div>
    </div>
  )
}

function Rack({ target, effects, catalog, run, sel, onSelect, project, player, revision }) {
  const [lib, setLib] = useState(false)
  const byName = Object.fromEntries((catalog || []).map(e => [e.name, e]))
  const aggiungi = async name => {
    setLib(false)
    try { localStorage.setItem('medit.fx.recent', JSON.stringify([name, ...recenti().filter(x => x !== name)].slice(0, 8))) } catch { /* */ }
    const r = await run('add_effect', { target, type: name })
    if (r) onSelect(r.result.index)
  }
  const valido = sel !== null && sel < effects.length
  return (
    <div className="rack-wrap">
      <div className="rack">
        <span className="rack-in" title="Signal flows left to right">IN</span>
        {effects.map((e, i) => <FxCard key={i} e={e} i={i} n={effects.length} spec={byName[e.type]} sel={sel === i}
          target={target} run={run} onSelect={onSelect} />)}
        <div className="fx-add-wrap">
          <button className="fx-add" onClick={() => setLib(!lib)}><Icon name="plus" size={16} /><span>Add effect</span></button>
          {lib && <FxLibrary catalog={catalog} onPick={aggiungi} onClose={() => setLib(false)} />}
        </div>
        <span className="rack-in" title="To the fader">OUT</span>
      </div>
      <div className="rack-editor">
        {valido
          ? <FxPanel embedded project={project} target={target} index={sel} catalog={catalog} run={run} player={player} revision={revision} />
          : <p className="hint pad">{effects.length ? 'Click an effect to open all its controls here.' : 'No effects yet: pick a preset above, or add an effect. Order matters: EQ → compressor → saturation → modulation → delay/reverb.'}</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- ingresso e registrazione

function InputRow({ track, recorder, rec, countdown, armed, onArm, onRecord, project, player }) {
  const [devs, setDevs] = useState([])
  const [, bump] = useState(0)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const bar = useRef(null), clip = useRef(null), peakRef = useRef(0)
  const r = recorder()
  const aggiorna = () => bump(x => x + 1)
  useEffect(() => { Recorder.devices().then(setDevs) }, [r.isOpen])
  // meter: legge il picco a ogni frame finche' il microfono e' aperto
  useEffect(() => {
    let raf = 0, hold = 0
    const tick = () => {
      const p = r.isOpen ? r.peak() : 0
      peakRef.current = Math.max(p, peakRef.current * 0.92)
      if (bar.current) bar.current.style.width = `${Math.min(100, Math.max(0, (1 + 20 * Math.log10(Math.max(peakRef.current, 1e-4)) / 60)) * 100)}%`
      if (p >= 0.98) hold = 90
      if (clip.current) clip.current.classList.toggle('on', hold-- > 0)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [r])
  const apri = async () => {
    setErr('')
    try { if (r.isOpen) r.close(); else await r.open() } catch (e) {
      setErr(e.name === 'NotAllowedError' ? 'Microphone blocked: allow it in the browser' : e.message || e.name)
    }
    aggiorna()
  }
  const monitor = async on => {
    if (on && !r.isOpen) await apri()
    r.setMonitor({ on })
    aggiorna()
  }
  const calibra = async () => {
    setErr(''); setBusy('calibrating')
    try { await r.calibrate() } catch (e) { setErr(e.message) }
    setBusy(''); aggiorna()
  }
  const recording = rec === 'rec' || rec === 'count'
  return (
    <div className="input-row">
      <button className={'arm' + (armed ? ' on' : '')} title="Arm: the transport Rec records onto this track" onClick={onArm}>R</button>
      <Icon name="mic" size={14} />
      <select className="dev" value={r.deviceId} title="Input" onChange={async e => { await r.setDevice(e.target.value); aggiorna() }}>
        <option value="">Default input</option>
        {devs.filter(d => d.id && d.id !== 'default').map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <div className={'in-meter' + (r.isOpen ? '' : ' idle')} title="Input level · red = clipping: move away or lower the input gain"><i ref={bar} /><b ref={clip} /></div>
      <button className={r.isOpen ? 'on' : ''} onClick={apri} title="Open the microphone to see the level and hear yourself">{r.isOpen ? 'Input on' : 'Input off'}</button>
      <span className="sep" />
      <button className={'mon' + (r.monitor.on ? ' on' : '')} title="Monitoring: hear yourself while you sing. Use headphones, or it will feed back."
        onClick={() => monitor(!r.monitor.on)}><Icon name="headphones" size={13} /> Monitor</button>
      {r.monitor.on && <>
        <label className="check" title="A touch of reverb in your headphones only (it is not recorded)"><input type="checkbox" checked={r.monitor.reverb}
          onChange={e => { r.setMonitor({ reverb: e.target.checked }); aggiorna() }} /> Reverb</label>
        <input type="range" className="mon-vol" min={0} max={1.5} step={0.05} value={r.monitor.volume} title="Monitor volume"
          onChange={e => { r.setMonitor({ volume: Number(e.target.value) }); aggiorna() }} />
      </>}
      <span className="sep" />
      <button disabled={!!busy || recording} onClick={calibra}
        title="Measure the latency: speakers on (no headphones), quiet room. Takes then land exactly on the beat.">
        {busy ? 'Listening…' : 'Calibrate'}</button>
      <span className="hint" title={r.calibrated !== null ? 'Measured latency' : 'Estimated latency (calibrate to measure it)'}>
        {Math.round(r.latency() * 1000)} ms{r.calibrated !== null ? '' : ' est.'}</span>
      {r.calibrated !== null && <button className="link" onClick={() => { r.resetCalibration(); aggiorna() }}>reset</button>}
      <span className="grow" />
      {err && <span className="warn ellipsis" title={err}>{err}</span>}
      <button className={'rec-big' + (recording ? ' on' : '')} disabled={rec === 'arming' || rec === 'saving'}
        title={recording ? 'Stop (Space)' : 'Record onto this track from the playhead (R)'} onClick={() => onRecord(track.id)}>
        <i />{rec === 'count' ? `Count-in ${countdown}` : rec === 'rec' ? 'Stop' : rec === 'saving' ? 'Saving…' : 'Record'}</button>
    </div>
  )
}

// testo della sezione sotto il cursore: da leggere mentre si canta
function LyricsPane({ project, player }) {
  const [sec, setSec] = useState(null)
  const spb = 60 / project.bpm, bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const secs = project.sections
  useEffect(() => player.onFrame(t => {
    const bar = t / spb / bpb + 1
    const s = secs.find(s => bar >= s.bar && bar < s.bar + s.bars)
    setSec(x => (x?.id === s?.id && x?.lyrics === s?.lyrics ? x : s || null))
  }), [player, secs, spb, bpb])
  const prossima = sec ? secs.find(s => s.bar >= sec.bar + sec.bars) : secs[0]
  return (
    <div className="lyrics-pane">
      <h4>{sec ? sec.name : 'Lyrics'}</h4>
      {sec?.lyrics ? <pre>{sec.lyrics}</pre> : <p className="hint">{secs.some(s => s.lyrics) ? 'No lyrics in this section.' : 'Write lyrics in a section (click its marker), or ask the Assistant.'}</p>}
      {prossima?.lyrics && <div className="next"><small>next · {prossima.name}</small><pre>{prossima.lyrics.split('\n')[0]}</pre></div>}
    </div>
  )
}

// ---------------------------------------------------------------- pannello

export default function Dock({ project, sel, view, setView, fxIndex, setFxIndex, catalog, run, player, revision, height,
  recorder, rec, countdown, armed, onArm, onRecord, analysis, onAnalyze, onOpenClip, playheadBar, setSelection, onOpenFx, onClose }) {
  // la traccia di cui si parla: selezionata, o quella della clip selezionata
  const track = useMemo(() => {
    if (!sel) return null
    const id = sel.kind === 'track' ? sel.id : sel.track
    return project.tracks.find(t => t.id === id) || (sel.kind === 'clip' ? project.tracks.find(t => t.clips.some(c => c.id === sel.id)) : null)
  }, [sel, project])
  const clip = sel?.kind === 'clip' ? track?.clips.find(c => c.id === sel.id) : null
  const section = sel?.kind === 'section' ? project.sections.find(s => s.id === sel.id) : null
  const mode = view === 'mixer' ? 'mixer' : view === 'master' || (!track && !section) ? 'master' : section ? 'section' : 'track'
  const target = mode === 'master' ? 'master' : track?.id
  const effects = mode === 'master' ? project.master.effects : track?.effects || []
  const tabs = mode === 'master' ? [['effects', 'Effects'], ['mastering', 'Mastering']]
    : mode === 'track' ? [['effects', 'Effects'], ...(track.kind === 'midi' ? [['sound', 'Sound']] : []), ['track', 'Track'],
      ...(clip ? [['clip', 'Clip']] : []), ...(track.kind === 'audio' ? [['lyrics', 'Lyrics']] : [])] : []
  const [tab, setTab] = useState('effects')
  useEffect(() => { if (clip) setTab('clip') }, [clip?.id])
  useEffect(() => { if (!tabs.some(([k]) => k === tab)) setTab('effects') })
  const chains = catalog.chains || []
  const nome = mode === 'master' ? 'Master' : mode === 'mixer' ? 'Mixer' : mode === 'section' ? section.name : track.name

  return (
    <div className="dock" style={{ height }}>
      <div className="dock-head">
        <button className="icon-btn" title="Close the panel (Esc)" onClick={onClose}>✕</button>
        <span className="dock-name" style={{ '--c': track?.color && mode === 'track' ? track.color : 'var(--accent)' }}>
          {mode === 'track' && <Icon name={track.kind === 'audio' ? 'wave' : track.kind === 'bus' ? 'sliders' : 'piano'} size={13} />}{nome}</span>
        {(mode === 'track' || mode === 'master') && <>
          <PresetBar target={target} track={track} effects={effects} chains={chains} run={run} />
          <QuickKnobs target={target} track={mode === 'track' ? track : null} project={project} effects={effects} run={run} />
        </>}
        <span className="grow" />
        {tabs.length > 0 && <div className="dock-tabs">
          {tabs.map(([k, n]) => <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}</button>)}</div>}
        <span className="sep" />
        <button className={mode === 'mixer' ? 'on' : ''} title="All channels" onClick={() => setView(mode === 'mixer' ? 'track' : 'mixer')}><Icon name="sliders" size={13} /> Mixer</button>
        <button className={mode === 'master' ? 'on' : ''} title="Master effects and mastering" onClick={() => setView(mode === 'master' ? 'track' : 'master')}>Master</button>
      </div>
      {mode === 'track' && track.kind === 'audio' && <InputRow track={track} recorder={recorder} rec={rec} countdown={countdown}
        armed={armed === track.id} onArm={() => onArm(armed === track.id ? null : track.id)} onRecord={onRecord} project={project} player={player} />}
      <div className="dock-body">
        {mode === 'mixer' && <Mixer project={project} run={run} selection={sel} setSelection={s => { setSelection(s); setView('track') }}
          analysis={analysis} onAnalyze={onAnalyze} fx={null} onOpenFx={onOpenFx} />}
        {mode === 'section' && <SectionInspector section={section} run={run} />}
        {(mode === 'track' || mode === 'master') && tab === 'effects' &&
          <Rack target={target} effects={effects} catalog={catalog.effects} run={run} sel={fxIndex} onSelect={setFxIndex}
            project={project} player={player} revision={revision} />}
        {mode === 'master' && tab === 'mastering' && <MasterKnobs project={project} run={run} analysis={analysis} onAnalyze={onAnalyze} />}
        {mode === 'track' && tab === 'sound' && <SoundPanel track={track} catalog={catalog} run={run} />}
        {mode === 'track' && tab === 'track' && <TrackPanel track={track} project={project} run={run} />}
        {mode === 'track' && tab === 'clip' && clip && <ClipPanel clip={clip} track={track} project={project} run={run} playheadBar={playheadBar} onOpen={() => onOpenClip(clip.id)} />}
        {mode === 'track' && tab === 'lyrics' && <LyricsPane project={project} player={player} />}
      </div>
    </div>
  )
}
