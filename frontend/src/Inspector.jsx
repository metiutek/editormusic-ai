// Proprieta' di cio' che e' selezionato: traccia, clip, sezione o master.
// Gli slider mandano l'operazione al rilascio: un gesto = un undo.
import { useEffect, useState } from 'react'
import Icon from './Icons.jsx'
import { fmtNum, rangeFor, stepFor, titleCase } from './util.js'

export function Slider({ label, value, min, max, step, unit = '', onCommit, title }) {
  const [v, setV] = useState(value)
  useEffect(() => { setV(value) }, [value])
  return (
    <label className="slider" title={title}>
      <span className="sl-label">{label}</span>
      <input type="range" min={min} max={max} step={step} value={v ?? 0}
        onChange={e => setV(Number(e.target.value))}
        onPointerUp={() => v !== value && onCommit(v)} onKeyUp={() => v !== value && onCommit(v)} />
      <input className="sl-num" type="number" step={step} value={v ?? 0} onChange={e => setV(Number(e.target.value))}
        onBlur={() => v !== value && onCommit(v)} onKeyDown={e => e.key === 'Enter' && v !== value && onCommit(v)} />
      {unit && <span className="unit">{unit}</span>}
    </label>
  )
}

function Field({ label, children }) {
  return <label className="field"><span>{label}</span>{children}</label>
}

function TextCommit({ value, onCommit, ...rest }) {
  const [v, setV] = useState(value ?? '')
  useEffect(() => { setV(value ?? '') }, [value])
  return <input value={v} onChange={e => setV(e.target.value)} onBlur={() => v !== value && onCommit(v)}
    onKeyDown={e => e.key === 'Enter' && e.target.blur()} {...rest} />
}

export function EffectChain({ target, effects, catalog, chains, run }) {
  const [add, setAdd] = useState('')
  const [open, setOpen] = useState(null)
  const byName = Object.fromEntries((catalog || []).map(e => [e.name, e]))
  return (
    <div className="chain">
      <h4><Icon name="sliders" size={13} /> Effects</h4>
      {!effects.length && <p className="hint">No effects. Order matters: EQ → compressor → saturation → modulation → delay/reverb.</p>}
      {effects.map((e, i) => {
        const spec = byName[e.type]
        const params = { ...Object.fromEntries(Object.entries(spec?.params || {}).map(([k, p]) => [k, p.default])), ...(e.params || {}) }
        return (
          <div key={i} className={'fx' + (e.enabled === false ? ' off' : '')}>
            <div className="fx-head">
              <input type="checkbox" checked={e.enabled !== false} title="On/off"
                onChange={ev => run('update_effect', { target, index: i, enabled: ev.target.checked })} />
              <b className="grow" onClick={() => setOpen(open === i ? null : i)}>{titleCase(e.type)}</b>
              <button className="icon-btn" title="Move up" disabled={i === 0} onClick={() => run('move_effect', { target, index: i, to: i - 1 })}><Icon name="up" size={12} /></button>
              <button className="icon-btn" title="Move down" disabled={i === effects.length - 1} onClick={() => run('move_effect', { target, index: i, to: i + 1 })}><Icon name="down" size={12} /></button>
              <button className="icon-btn" title="Remove" onClick={() => run('remove_effect', { target, index: i })}><Icon name="trash" size={12} /></button>
            </div>
            {open === i && spec && Object.entries(spec.params).map(([k, p]) => {
              if (p.type === 'bool') return (
                <label key={k} className="check"><input type="checkbox" checked={!!params[k]}
                  onChange={ev => run('update_effect', { target, index: i, params: { [k]: ev.target.checked } })} /> {p.desc || k}</label>)
              if (p.type === 'choice') return (
                <Field key={k} label={k}><select value={params[k]} onChange={ev => run('update_effect', { target, index: i, params: { [k]: ev.target.value } })}>
                  {p.choices.map(c => <option key={c}>{c}</option>)}</select></Field>)
              return <Slider key={k} label={k} title={p.desc} value={params[k]} min={p.min ?? 0} max={p.max ?? 1} step={stepFor(p)} unit={p.unit}
                onCommit={v => run('update_effect', { target, index: i, params: { [k]: v } })} />
            })}
          </div>)
      })}
      <div className="row">
        <select className="grow" value={add} onChange={e => setAdd(e.target.value)}>
          <option value="">+ effect…</option>
          {(catalog || []).map(e => <option key={e.name} value={e.name}>{titleCase(e.name)} — {e.desc}</option>)}
        </select>
        <button disabled={!add} onClick={() => { run('add_effect', { target, type: add }); setOpen(effects.length); setAdd('') }}>Add</button>
      </div>
      <div className="row">
        <select className="grow" defaultValue="" onChange={e => { if (e.target.value) run('apply_chain', { target, name: e.target.value }); e.target.value = '' }}>
          <option value="">+ ready chain…</option>
          {(chains || []).map(c => <option key={c.name} value={c.name}>{c.name} — {c.desc}</option>)}
        </select>
        {effects.length > 0 && <button title="Save this chain to reuse it in every song"
          onClick={() => { const n = prompt('Name of the chain'); if (n) run('save_chain', { name: n, target }) }}>Save</button>}
      </div>
    </div>
  )
}

function Instrument({ track, catalog, run }) {
  const [open, setOpen] = useState(false)
  const tipo = track.instrument_type
  const params = track.instrument_params || {}
  const spec = catalog.instruments?.[tipo] || {}
  const cats = {}
  for (const s of catalog.sounds || []) (cats[s.category] ||= []).push(s)
  return (
    <div className="instrument">
      <h4><Icon name="piano" size={13} /> Sound</h4>
      <select value={track.instrument} onChange={e => run('set_instrument', { track: track.id, sound: e.target.value })}>
        {!catalog.sounds?.some(s => s.name === track.instrument) && <option value={track.instrument}>{track.instrument}</option>}
        {Object.entries(cats).map(([c, list]) => <optgroup key={c} label={c}>
          {list.map(s => <option key={s.name} value={s.name}>{s.name}{s.user ? ' ★' : ''}</option>)}</optgroup>)}
      </select>
      <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Shape the sound'} ({tipo})</button>
      {open && <div className="params">
        {Object.entries(spec).map(([k, d]) => {
          const v = params[k] ?? d.default
          if (typeof d.default === 'string' || k === 'osc1' || k === 'osc2' || k === 'filter') {
            const opts = k === 'filter' ? ['lowpass', 'highpass', 'bandpass', 'none'] : ['saw', 'square', 'triangle', 'sine', 'noise']
            return <Field key={k} label={k}><select value={v} onChange={e => run('set_instrument', { track: track.id, params: { [k]: e.target.value } })}>
              {opts.map(o => <option key={o}>{o}</option>)}</select></Field>
          }
          if (typeof d.default === 'boolean') return <label key={k} className="check"><input type="checkbox" checked={!!v}
            onChange={e => run('set_instrument', { track: track.id, params: { [k]: e.target.checked } })} /> {k}</label>
          if (typeof d.default !== 'number') return null
          const [lo, hi] = rangeFor(k, d.default)
          return <Slider key={k} label={k} title={d.desc} value={v} min={lo} max={hi} step={hi - lo > 30 ? 1 : hi - lo > 2 ? 0.1 : 0.01}
            onCommit={x => run('set_instrument', { track: track.id, params: { [k]: x } })} />
        })}
        <button onClick={() => { const n = prompt('Name of your sound'); if (n) run('save_sound', { name: n, track: track.id }) }}>Save as my sound</button>
      </div>}
    </div>
  )
}

function TrackInspector({ track, project, catalog, run }) {
  const buses = project.tracks.filter(t => t.kind === 'bus' && t.id !== track.id)
  const sends = Object.fromEntries((track.sends || []).map(s => [s.bus, s.level_db]))
  return (
    <div className="inspector">
      <div className="row">
        <input type="color" value={track.color || '#4f8fd9'} onChange={e => run('set_track', { track: track.id, color: e.target.value })} />
        <TextCommit className="grow" value={track.name} onCommit={v => run('set_track', { track: track.id, name: v })} />
      </div>
      <div className="row">
        <button className={track.mute ? 'on' : ''} onClick={() => run('set_track', { track: track.id, mute: !track.mute })}>Mute</button>
        <button className={track.solo ? 'on' : ''} onClick={() => run('set_track', { track: track.id, solo: !track.solo })}>Solo</button>
        <Field label="Role"><select value={track.role || ''} onChange={e => run('set_track', { track: track.id, role: e.target.value })}>
          {['', 'drums', 'bass', 'chords', 'pad', 'lead', 'vocal', 'arp', 'fx'].map(r => <option key={r} value={r}>{r || '—'}</option>)}</select></Field>
      </div>
      <Slider label="Volume" value={track.volume_db} min={-60} max={12} step={0.5} unit="dB" onCommit={v => run('set_track', { track: track.id, volume_db: v })} />
      <Slider label="Pan" value={track.pan || 0} min={-1} max={1} step={0.05} onCommit={v => run('set_track', { track: track.id, pan: v })} />
      {track.kind === 'midi' && <Instrument track={track} catalog={catalog} run={run} />}
      <EffectChain target={track.id} effects={track.effects || []} catalog={catalog.effects} chains={catalog.chains} run={run} />
      {track.kind !== 'bus' && <div className="sends">
        <h4>Sends</h4>
        {!buses.length && <p className="hint">No buses. A bus shares one reverb or delay among many tracks.
          <button className="link" onClick={() => run('add_bus', { name: 'Reverb' })}>Add a reverb bus</button></p>}
        {buses.map(b => sends[b.id] !== undefined
          ? <div key={b.id} className="row"><Slider label={b.name} value={sends[b.id]} min={-40} max={0} step={0.5} unit="dB"
            onCommit={v => run('set_send', { track: track.id, bus: b.id, level_db: v })} />
            <button className="icon-btn" title="Stop sending" onClick={() => run('set_send', { track: track.id, bus: b.id, remove: true })}>✕</button></div>
          : <button key={b.id} onClick={() => run('set_send', { track: track.id, bus: b.id, level_db: -12 })}>+ send to {b.name}</button>)}
      </div>}
      {track.automation?.length > 0 && <div className="autom">
        <h4>Automation</h4>
        {track.automation.map(a => <div key={a.target} className="row"><span className="grow">{a.target}</span>
          <span className="hint">{Array.isArray(a.points) ? a.points.length : a.points} points</span>
          <button className="icon-btn" title="Remove" onClick={() => run('clear_automation', { track: track.id, target: a.target })}>✕</button></div>)}
      </div>}
      <div className="row">
        <button onClick={() => run('duplicate_track', { track: track.id })}><Icon name="copy" size={13} /> Duplicate</button>
        <button onClick={() => { if (confirm(`Delete the track "${track.name}"?`)) run('remove_track', { track: track.id }) }}><Icon name="trash" size={13} /> Delete</button>
      </div>
    </div>
  )
}

function ClipInspector({ clip, track, run, playheadBar, onOpen }) {
  const id = clip.id
  return (
    <div className="inspector">
      <div className="row"><TextCommit className="grow" value={clip.name} onCommit={v => run('set_clip', { clip: id, name: v })} /></div>
      <p className="hint">{track.name} · {track.kind === 'midi' ? `${clip.notes} notes ${clip.range || ''}` : `audio`}</p>
      <div className="grid2">
        <Field label="Bar"><TextCommit type="number" value={clip.bar} onCommit={v => run('set_clip', { clip: id, bar: Number(v) })} /></Field>
        <Field label="Bars"><TextCommit type="number" value={clip.bars} onCommit={v => run('set_clip', { clip: id, bars: Number(v) })} /></Field>
        <Field label="Loop every (bars, 0 = off)"><TextCommit type="number" value={clip.loop_bars || 0} onCommit={v => run('set_clip', { clip: id, loop_bars: Number(v) })} /></Field>
        <Field label="Transpose"><TextCommit type="number" value={clip.transpose || 0} onCommit={v => run('set_clip', { clip: id, transpose: Number(v) })} /></Field>
      </div>
      <Slider label="Gain" value={clip.gain_db || 0} min={-24} max={12} step={0.5} unit="dB" onCommit={v => run('set_clip', { clip: id, gain_db: v })} />
      <Slider label="Fade in" value={clip.fade_in || 0} min={0} max={16} step={0.25} unit="beats" onCommit={v => run('set_clip', { clip: id, fade_in: v })} />
      <Slider label="Fade out" value={clip.fade_out || 0} min={0} max={16} step={0.25} unit="beats" onCommit={v => run('set_clip', { clip: id, fade_out: v })} />
      {track.kind === 'audio' && <Slider label="Start in file" value={clip.offset_s || 0} min={0} max={600} step={0.01} unit="s"
        onCommit={v => run('set_clip', { clip: id, offset: v })} />}
      <div className="row wrap">
        {track.kind === 'midi' && <button className="primary" onClick={onOpen}><Icon name="piano" size={13} /> Edit notes</button>}
        <button onClick={() => run('set_clip', { clip: id, muted: !clip.muted })}>{clip.muted ? 'Unmute' : 'Mute'}</button>
        <button disabled={!(playheadBar > clip.bar && playheadBar < clip.bar + clip.bars)} title="Split at the playhead"
          onClick={() => run('split_clip', { clip: id, at_bar: playheadBar })}><Icon name="scissors" size={13} /> Split</button>
        <button title="Copy after itself (Ctrl+D)" onClick={() => run('duplicate_clip', { clip: id })}><Icon name="copy" size={13} /> Duplicate</button>
        <button title="Delete (Del)" onClick={() => run('remove_clip', { clip: id })}><Icon name="trash" size={13} /></button>
      </div>
    </div>
  )
}

function SectionInspector({ section, run }) {
  const id = section.id
  return (
    <div className="inspector">
      <div className="row"><TextCommit className="grow" value={section.name} onCommit={v => run('set_section', { section: id, name: v })} /></div>
      <div className="grid2">
        <Field label="Bar"><TextCommit type="number" value={section.bar} onCommit={v => run('set_section', { section: id, bar: Number(v) })} /></Field>
        <Field label="Bars"><TextCommit type="number" value={section.bars} onCommit={v => run('set_section', { section: id, bars: Number(v) })} /></Field>
      </div>
      <Lyrics section={section} run={run} />
      <div className="row">
        <button onClick={() => run('copy_bars', { from_bar: section.bar, bars: section.bars, to_bar: section.bar + section.bars })}
          title="Insert-free copy of everything in this section right after it">Repeat after</button>
        <button onClick={() => run('remove_section', { section: id })}><Icon name="trash" size={13} /> Remove marker</button>
      </div>
    </div>
  )
}

function Lyrics({ section, run }) {
  const [t, setT] = useState(section.lyrics || '')
  useEffect(() => { setT(section.lyrics || '') }, [section.id, section.lyrics])
  return (
    <label className="field wide"><span>Lyrics (one line per phrase)</span>
      <textarea rows={8} value={t} onChange={e => setT(e.target.value)}
        onBlur={() => t !== (section.lyrics || '') && run('set_section', { section: section.id, lyrics: t })} /></label>
  )
}

function MasterInspector({ project, catalog, run, analysis, onAnalyze }) {
  const [lufs, setLufs] = useState(-14)
  return (
    <div className="inspector">
      <h4>Master</h4>
      <Slider label="Volume" value={project.master.volume_db} min={-24} max={12} step={0.5} unit="dB" onCommit={v => run('set_master', { volume_db: v })} />
      <EffectChain target="master" effects={project.master.effects || []} catalog={catalog.effects} chains={catalog.chains} run={run} />
      <h4>Mastering</h4>
      <div className="row">
        <Field label="Target LUFS"><input type="number" value={lufs} step={1} onChange={e => setLufs(Number(e.target.value))} /></Field>
        <button className="primary" onClick={() => run('auto_master', { target_lufs: lufs })}>Auto master</button>
        <button onClick={onAnalyze}>Measure</button>
      </div>
      <p className="hint">-14 LUFS for streaming, -9 for club. Ceiling -1 dBTP.</p>
      {analysis && <Measures a={analysis} />}
    </div>
  )
}

export function Measures({ a }) {
  if (!a || a.empty) return null
  return (
    <div className="measures">
      <div className="kv"><span>Loudness</span><b>{fmtNum(a.lufs)} LUFS</b></div>
      <div className="kv"><span>True peak</span><b className={a.true_peak_db > -1 ? 'bad' : ''}>{fmtNum(a.true_peak_db)} dBTP</b></div>
      <div className="kv"><span>Range (LRA)</span><b>{fmtNum(a.lra)} LU</b></div>
      <div className="kv"><span>Crest</span><b>{fmtNum(a.crest_db)} dB</b></div>
      {a.bands_db && <div className="bands">{Object.entries(a.bands_db).map(([k, v]) => (
        <div key={k} className="band" title={`${k}: ${v} dB`}><div style={{ height: `${Math.max(2, 100 + v * 4)}%` }} /><small>{k.replace('_', ' ')}</small></div>))}</div>}
    </div>
  )
}

export default function Inspector({ project, selection, catalog, run, playheadBar, onOpenClip, analysis, onAnalyze }) {
  if (selection?.kind === 'clip') {
    for (const t of project.tracks) {
      const c = t.clips.find(c => c.id === selection.id)
      if (c) return <ClipInspector clip={c} track={t} run={run} playheadBar={playheadBar} onOpen={() => onOpenClip(c.id)} />
    }
  }
  if (selection?.kind === 'track') {
    const t = project.tracks.find(t => t.id === selection.id)
    if (t) return <TrackInspector track={t} project={project} catalog={catalog} run={run} />
  }
  if (selection?.kind === 'section') {
    const s = project.sections.find(s => s.id === selection.id)
    if (s) return <SectionInspector section={s} run={run} />
  }
  return <MasterInspector project={project} catalog={catalog} run={run} analysis={analysis} onAnalyze={onAnalyze} />
}
