// Linguette del pannello traccia, in forma grafica: la clip si vede (forma d'onda o note,
// con le dissolvenze disegnate sopra) e si regola con le manopole; la traccia e' un
// canale (volume, pan, mandate a manopola, colori, ruolo); il suono ha i parametri a
// manopola; il master ha volume e loudness obiettivo. Numeri solo dove servono davvero.
import { useEffect, useState } from 'react'
import { MiniNotes, Waveform } from './Arrange.jsx'
import { Knob, useWidth } from './FxPanel.jsx'
import Icon from './Icons.jsx'
import { Measures } from './Inspector.jsx'
import { rangeFor, titleCase } from './util.js'

// valori "dal vivo" mentre si gira una manopola; si azzerano quando arriva lo stato nuovo
function useLive(dep) {
  const [live, setLive] = useState({})
  useEffect(() => { setLive({}) }, [dep])
  return [live, ch => setLive(l => ({ ...l, ...ch }))]
}

function K({ k, label, value, p, live, setLive, commit, size = 48, color }) {
  const v = live[k] ?? value
  return <Knob label={label} size={size} value={v} p={p} color={color}
    onChange={x => setLive({ [k]: x })} onCommit={x => { setLive({ [k]: x }); if (x !== value) commit(x) }} />
}

// numero compatto con frecce (posizione, lunghezza): si legge come un display
function Readout({ label, value, step = 1, min = -Infinity, onCommit, unit }) {
  const [v, setV] = useState(String(value))
  useEffect(() => { setV(String(value)) }, [value])
  const manda = x => { const n = Math.max(min, Math.round(Number(x) * 1000) / 1000); if (!Number.isNaN(n) && n !== value) onCommit(n); else setV(String(value)) }
  return (
    <div className="readout">
      <span>{label}</span>
      <button className="icon-btn" onClick={() => manda(value - step)}>‹</button>
      <input value={v} onChange={e => setV(e.target.value)} onBlur={() => manda(v)}
        onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter') e.target.blur() }} />
      <button className="icon-btn" onClick={() => manda(value + step)}>›</button>
      {unit && <small>{unit}</small>}
    </div>
  )
}

// ---------------------------------------------------------------- clip

// lavori lunghi (separazione, trascrizione): si vede da quanto stanno andando
export function useLavoro(run) {
  const [lav, setLav] = useState(null)       // {nome, t0}
  const [, tick] = useState(0)
  useEffect(() => {
    if (!lav) return
    const id = setInterval(() => tick(x => x + 1), 1000)
    return () => clearInterval(id)
  }, [lav])
  const vai = async (etichetta, op, body) => {
    setLav({ nome: etichetta, t0: Date.now() })
    try { await run(op, body) } finally { setLav(null) }
  }
  const s = lav ? Math.floor((Date.now() - lav.t0) / 1000) : 0
  const testo = lav ? `${lav.nome}… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : ''
  return [vai, testo]
}

export function ClipPanel({ clip, track, project, run, playheadBar, onOpen }) {
  const [live, setLive] = useLive(clip)
  const [ref, W, H] = useWidth()
  const bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const id = clip.id
  const set = ch => run('set_clip', { clip: id, ...ch })
  const val = k => live[k] ?? clip[k] ?? 0
  const beats = clip.bars * bpb
  const fi = Math.min(1, val('fade_in') / beats) * W, fo = Math.min(1, val('fade_out') / beats) * W
  const g = 10 ** (val('gain_db') / 20)
  const audio = track.kind === 'audio'
  const seconds = beats * 60 / project.bpm
  const dentro = playheadBar > clip.bar && playheadBar < clip.bar + clip.bars
  const [lavora, lavoro] = useLavoro(run)
  return (
    <div className="panel-clip">
      <div className="clip-preview" ref={ref} style={{ '--c': track.color }}>
        <div className="cp-wave" style={{ transform: `scaleY(${Math.min(g, 3)})` }}>
          {audio ? <Waveform clip={{ ...clip, offset_s: val('offset_s') }} seconds={seconds} w={W} h={H} />
            : <MiniNotes clip={clip} bpb={bpb} bars={clip.bars} w={W} h={H} />}
        </div>
        <svg className="cp-fades" width={W} height={H}>
          {fi > 0 && <><path d={`M0,0 L${fi},0 L0,${H} Z`} className="fade-shade" /><line x1={0} y1={H} x2={fi} y2={0} className="fade-line" /></>}
          {fo > 0 && <><path d={`M${W},0 L${W - fo},0 L${W},${H} Z`} className="fade-shade" /><line x1={W - fo} y1={0} x2={W} y2={H} className="fade-line" /></>}
        </svg>
        {clip.muted && <div className="cp-muted">muted</div>}
        <div className="cp-info">{clip.name} · {Math.round(clip.bars * 100) / 100} bars · {seconds.toFixed(1)} s</div>
      </div>
      <div className="panel-knobs">
        <K k="gain_db" label="Gain" value={clip.gain_db || 0} p={{ min: -24, max: 12, default: 0, unit: 'dB', desc: 'clip gain' }} live={live} setLive={setLive} commit={v => set({ gain_db: v })} />
        <K k="fade_in" label="Fade in" value={clip.fade_in || 0} p={{ min: 0, max: Math.max(1, Math.min(32, beats)), default: 0, unit: 'beats', desc: 'fade in' }} live={live} setLive={setLive} commit={v => set({ fade_in: v })} />
        <K k="fade_out" label="Fade out" value={clip.fade_out || 0} p={{ min: 0, max: Math.max(1, Math.min(32, beats)), default: 0, unit: 'beats', desc: 'fade out' }} live={live} setLive={setLive} commit={v => set({ fade_out: v })} />
        {audio && <K k="offset_s" label="Start in file" value={clip.offset_s || 0} p={{ min: 0, max: 600, default: 0, unit: 's', desc: 'where the clip starts inside the file' }} live={live} setLive={setLive} commit={v => set({ offset: v })} />}
        <K k="transpose" label={audio ? 'Pitch' : 'Transpose'} value={clip.transpose || 0} p={{ min: -24, max: 24, default: 0, unit: 'st', desc: 'semitones' }} live={live} setLive={setLive} commit={v => set({ transpose: Math.round(v) })} />
        {!audio && <K k="loop_bars" label="Loop" value={clip.loop_bars || 0} p={{ min: 0, max: 16, default: 0, unit: 'bars', desc: 'repeat every N bars (0 = off)' }} live={live} setLive={setLive} commit={v => set({ loop_bars: Math.round(v) })} />}
      </div>
      <div className="panel-foot">
        <Readout label="Start bar" value={clip.bar} min={1} onCommit={v => set({ bar: v })} />
        <Readout label="Length" value={Math.round(clip.bars * 1000) / 1000} min={0.25} onCommit={v => set({ bars: v })} unit="bars" />
        <span className="grow" />
        {lavoro && <span className="busy" title="It keeps going even if you edit; a full song can take a few minutes">{lavoro}</span>}
        {audio && <button disabled={!!lavoro} title="Vocals and backing on two new tracks (UVR / Demucs); this clip is muted, nothing is lost"
          onClick={() => lavora('Separating', 'separate_stems', { clip: id })}><Icon name="scissors" size={13} /> Separate vocals</button>}
        {audio && <button disabled={!!lavoro} title="Singing, humming or a solo → MIDI notes on a new track"
          onClick={() => lavora('Transcribing', 'audio_to_midi', { clip: id })}>Melody → MIDI</button>}
        {!audio && <button className="primary" onClick={onOpen}><Icon name="piano" size={13} /> Edit notes</button>}
        <button className={clip.muted ? 'on' : ''} onClick={() => set({ muted: !clip.muted })}>{clip.muted ? 'Unmute' : 'Mute'}</button>
        <button disabled={!dentro} title="Split at the playhead" onClick={() => run('split_clip', { clip: id, at_bar: playheadBar })}><Icon name="scissors" size={13} /> Split</button>
        <button title="Copy after itself (Ctrl+D)" onClick={() => run('duplicate_clip', { clip: id })}><Icon name="copy" size={13} /> Duplicate</button>
        <button title="Delete (Del)" onClick={() => run('remove_clip', { clip: id })}><Icon name="trash" size={13} /></button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- traccia

const COLORI = ['#e05a5a', '#e08a3c', '#d9b93a', '#7cc35a', '#3fb6a8', '#4f8fd9', '#8a6be0', '#d0609e', '#9497aa']
const RUOLI = ['drums', 'bass', 'chords', 'pad', 'lead', 'vocal', 'arp', 'fx']

export function TrackPanel({ track, project, run }) {
  const [live, setLive] = useLive(track)
  const [nome, setNome] = useState(track.name)
  useEffect(() => { setNome(track.name) }, [track.name])
  const buses = project.tracks.filter(t => t.kind === 'bus' && t.id !== track.id)
  const sends = Object.fromEntries((track.sends || []).map(s => [s.bus, s.level_db]))
  const st = ch => run('set_track', { track: track.id, ...ch })
  return (
    <div className="panel-track">
      <section className="pt-channel">
        <h5>Channel</h5>
        <div className="panel-knobs">
          <K k="volume_db" label="Volume" size={64} value={track.volume_db} p={{ min: -60, max: 12, default: 0, unit: 'dB', desc: 'fader' }} live={live} setLive={setLive} commit={v => st({ volume_db: v })} />
          <K k="pan" label="Pan" size={52} value={track.pan || 0} p={{ min: -1, max: 1, default: 0, desc: 'left / right' }} live={live} setLive={setLive} commit={v => st({ pan: v })} />
        </div>
        <div className="row">
          <button className={'ms' + (track.mute ? ' on' : '')} onClick={() => st({ mute: !track.mute })}>M</button>
          <button className={'ms solo' + (track.solo ? ' on' : '')} onClick={() => st({ solo: !track.solo })}>S</button>
        </div>
      </section>
      <section>
        <h5>Name & color</h5>
        <input className="pt-name" value={nome} onChange={e => setNome(e.target.value)} onBlur={() => nome.trim() && nome !== track.name && st({ name: nome.trim() })}
          onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter') e.target.blur() }} />
        <div className="swatches">{COLORI.map(c => <button key={c} className={track.color === c ? 'on' : ''} style={{ background: c }} title={c} onClick={() => st({ color: c })} />)}
          <input type="color" value={track.color || '#4f8fd9'} title="Any color" onChange={e => st({ color: e.target.value })} /></div>
        <h5>Role <small className="hint">(used by Balance mix and the Assistant)</small></h5>
        <div className="seg wrap">{RUOLI.map(r => <button key={r} className={track.role === r ? 'on' : ''} onClick={() => st({ role: track.role === r ? '' : r })}>{r}</button>)}</div>
      </section>
      {track.kind !== 'bus' && <section>
        <h5>Sends</h5>
        <div className="panel-knobs">
          {buses.map(b => sends[b.id] !== undefined
            ? <div key={b.id} className="send-k">
              <K k={'s' + b.id} label={b.name} value={sends[b.id]} p={{ min: -40, max: 0, default: -12, unit: 'dB', desc: 'send level' }} live={live} setLive={setLive}
                commit={v => run('set_send', { track: track.id, bus: b.id, level_db: v })} />
              <button className="link" onClick={() => run('set_send', { track: track.id, bus: b.id, remove: true })}>remove</button></div>
            : <button key={b.id} className="send-add" onClick={() => run('set_send', { track: track.id, bus: b.id, level_db: -12 })}>+ {b.name}</button>)}
          {!buses.length && <button className="send-add" onClick={() => run('add_bus', { name: 'Reverb' })}>+ Reverb bus</button>}
        </div>
      </section>}
      <section>
        <h5>Automation</h5>
        {!track.automation?.length && <p className="hint">None. Ask the Assistant: “fade the volume in over the intro”.</p>}
        {(track.automation || []).map(a => <div key={a.target} className="row"><span className="grow">{a.target}</span>
          <span className="hint">{Array.isArray(a.points) ? a.points.length : a.points} pts</span>
          <button className="icon-btn" title="Remove" onClick={() => run('clear_automation', { track: track.id, target: a.target })}>✕</button></div>)}
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={() => run('duplicate_track', { track: track.id })}><Icon name="copy" size={13} /> Duplicate</button>
          <button onClick={() => { if (confirm(`Delete the track "${track.name}"?`)) run('remove_track', { track: track.id }) }}><Icon name="trash" size={13} /> Delete</button>
        </div>
      </section>
    </div>
  )
}

// ---------------------------------------------------------------- suono

const unitaDi = k => (/cutoff|freq/.test(k) ? 'Hz' : /_ms$/.test(k) ? 'ms' : /_db$|gain/.test(k) ? 'dB' : '')

export function SoundPanel({ track, catalog, run }) {
  const tipo = track.instrument_type
  const params = track.instrument_params || {}
  const spec = catalog.instruments?.[tipo] || {}
  const [live, setLive] = useLive(track.instrument_params)
  const cats = {}
  for (const s of catalog.sounds || []) (cats[s.category] ||= []).push(s)
  const si = ch => run('set_instrument', { track: track.id, params: ch })
  const voci = Object.entries(spec)
  const scelte = voci.filter(([k, d]) => typeof d.default === 'string' || ['osc1', 'osc2', 'filter'].includes(k))
  const boole = voci.filter(([, d]) => typeof d.default === 'boolean')
  const numeri = voci.filter(([k, d]) => typeof d.default === 'number' && !['osc1', 'osc2', 'filter'].includes(k))
  return (
    <div className="panel-sound">
      <div className="row">
        <Icon name="piano" size={14} />
        <select value={track.instrument} onChange={e => run('set_instrument', { track: track.id, sound: e.target.value })}>
          {!catalog.sounds?.some(s => s.name === track.instrument) && <option value={track.instrument}>{track.instrument}</option>}
          {Object.entries(cats).map(([c, list]) => <optgroup key={c} label={c}>
            {list.map(s => <option key={s.name} value={s.name}>{s.name}{s.user ? ' ★' : ''}</option>)}</optgroup>)}
        </select>
        <span className="hint">engine: {tipo}</span>
        <span className="grow" />
        <button onClick={() => { const n = prompt('Name of your sound'); if (n) run('save_sound', { name: n, track: track.id }) }}>Save as my sound</button>
      </div>
      {scelte.length > 0 && <div className="sound-choices">{scelte.map(([k, d]) => {
        const opts = k === 'filter' ? ['lowpass', 'highpass', 'bandpass', 'none'] : ['saw', 'square', 'triangle', 'sine', 'noise']
        const v = params[k] ?? d.default
        return <div key={k} className="seg"><span className="hint">{titleCase(k)}</span>
          {opts.map(o => <button key={o} className={v === o ? 'on' : ''} onClick={() => si({ [k]: o })}>{o}</button>)}</div>
      })}
        {boole.map(([k, d]) => <button key={k} className={'fx-toggle' + ((params[k] ?? d.default) ? ' on' : '')} onClick={() => si({ [k]: !(params[k] ?? d.default) })}><i />{k}</button>)}
      </div>}
      <div className="panel-knobs">
        {numeri.map(([k, d]) => {
          const [lo, hi] = rangeFor(k, d.default)
          return <K key={k} k={k} label={titleCase(k.replace(/_(ms|db|hz)$/, ''))} value={params[k] ?? d.default}
            p={{ min: lo, max: hi, default: d.default, unit: unitaDi(k), desc: d.desc }} live={live} setLive={setLive} commit={v => si({ [k]: v })} />
        })}
        {!numeri.length && <p className="hint">This engine has no settings.</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- master

export function MasterKnobs({ project, run, analysis, onAnalyze }) {
  const [live, setLive] = useLive(project.master)
  const [lufs, setLufs] = useState(-14)
  return (
    <div className="panel-master">
      <div className="panel-knobs">
        <K k="volume_db" label="Master" size={64} value={project.master.volume_db} p={{ min: -24, max: 12, default: 0, unit: 'dB', desc: 'master volume' }}
          live={live} setLive={setLive} commit={v => run('set_master', { volume_db: v })} />
        <Knob label="Target" size={64} value={lufs} p={{ min: -24, max: -6, default: -14, unit: 'LUFS', desc: 'loudness to reach: -14 streaming, -9 club' }}
          onChange={setLufs} onCommit={setLufs} color="#ffb347" />
        <div className="pm-actions">
          <button className="primary" onClick={() => run('auto_master', { target_lufs: Math.round(lufs) })}>Auto master to {Math.round(lufs)} LUFS</button>
          <button onClick={onAnalyze}>Measure</button>
          <span className="hint">-14 streaming · -9 club · ceiling -1 dBTP</span>
        </div>
      </div>
      {analysis && <Measures a={analysis} />}
    </div>
  )
}
