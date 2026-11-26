// Mixer: un canale per traccia (volume, pan, mute, solo, misura), il master,
// e i pulsanti che misurano e sistemano: balance mix, review, auto master.
import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Measures } from './Inspector.jsx'
import { InlineEdit, useCommitOnRelease } from './Widgets.jsx'

// valore locale mentre si trascina, inviato una volta al rilascio
function useDrag(value, commit) {
  const [v, setV] = useState(null)
  useEffect(() => { setV(null) }, [value])
  const rel = useCommitOnRelease(x => { if (x !== value) commit(x); else setV(null) })
  return [v ?? value, {
    onPointerDown: rel.onPointerDown,
    onChange: e => { const x = Number(e.target.value); setV(x); rel.set(x) },
    onKeyUp: e => { const x = Number(e.target.value); if (x !== value) commit(x) },
    onDoubleClick: e => e.stopPropagation(),
  }]
}

// insert: gli effetti della catena, un clic apre il pannello in basso
function Inserts({ target, effects, fx, onOpenFx, slots = 0 }) {
  return (
    <div className="inserts" style={{ minHeight: slots * 19 }}>
      {effects.map((e, i) => <button key={i} title={`${e.type} · click to open`}
        className={(e.enabled === false ? 'off' : '') + (fx?.target === target && fx?.index === i ? ' on' : '')}
        onClick={ev => { ev.stopPropagation(); onOpenFx(target, i) }}>{e.type.replace(/_/g, ' ')}</button>)}
    </div>
  )
}

function Strip({ t, run, lufs, selected, onSelect, fx, onOpenFx, slots }) {
  const [edit, setEdit] = useState(false)
  const [vol, volProps] = useDrag(t.volume_db, x => run('set_track', { track: t.id, volume_db: x }))
  const [pan, panProps] = useDrag(t.pan || 0, x => run('set_track', { track: t.id, pan: x }))
  return (
    <div className={'strip' + (selected ? ' sel' : '')} onClick={onSelect} style={{ '--c': t.color }}>
      {edit
        ? <InlineEdit className="strip-edit" value={t.name} onCommit={n => { setEdit(false); run('set_track', { track: t.id, name: n }) }} onCancel={() => setEdit(false)} />
        : <div className="strip-name" title={t.name + ' · double-click to rename'} onDoubleClick={() => setEdit(true)}>{t.name}</div>}
      <Inserts target={t.id} effects={t.effects || []} fx={fx} onOpenFx={onOpenFx} slots={slots} />
      <input type="range" className="pan" min={-1} max={1} step={0.05} value={pan} title={`pan ${pan} · double-click: center`}
        {...panProps} onDoubleClick={e => { e.stopPropagation(); if (t.pan) run('set_track', { track: t.id, pan: 0 }) }} />
      <div className="fader-wrap">
        <input type="range" className="fader" min={-60} max={12} step={0.5} value={vol} title="double-click: 0 dB"
          {...volProps} onDoubleClick={e => { e.stopPropagation(); if (t.volume_db) run('set_track', { track: t.id, volume_db: 0 }) }} />
      </div>
      <div className="db">{vol > 0 ? '+' : ''}{vol}</div>
      <div className="row">
        <button className={'ms' + (t.mute ? ' on' : '')} onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, mute: !t.mute }) }}>M</button>
        <button className={'ms solo' + (t.solo ? ' on' : '')} onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, solo: !t.solo }) }}>S</button>
      </div>
      {lufs !== undefined && <div className="hint">{lufs} LU</div>}
    </div>
  )
}

export default function Mixer({ project, run, selection, setSelection, analysis, onAnalyze, fx, onOpenFx }) {
  const [levels, setLevels] = useState({})
  const [review, setReview] = useState(null)
  const [busy, setBusy] = useState('')
  // stessa altezza per gli insert di tutti i canali: i fader restano allineati
  const slots = Math.max(1, project.master.effects.length, ...project.tracks.map(t => (t.effects || []).length))
  const misura = async () => {
    setBusy('measuring')
    const out = {}
    try {
      for (const t of project.tracks) {
        const r = await api(`/api/analyze?track=${encodeURIComponent(t.id)}`)
        out[t.id] = r.lufs
      }
      setLevels(out)
      await onAnalyze()
    } catch { /* traccia vuota o muta */ }
    setBusy('')
  }
  const controlla = async () => {
    setBusy('checking')
    try { setReview(await api('/api/review')) } catch (e) { setReview({ warnings: [{ code: 'error', message: e.message }] }) }
    setBusy('')
  }
  return (
    <div className="mixer">
      <div className="row wrap">
        <button title="Set each track to a typical level for its role" onClick={() => run('balance_mix', {})}>Balance mix</button>
        <button disabled={!!busy} onClick={misura}>{busy === 'measuring' ? 'Measuring…' : 'Measure'}</button>
        <button disabled={!!busy} onClick={controlla}>{busy === 'checking' ? 'Checking…' : 'Review song'}</button>
        <button className="primary" onClick={() => run('auto_master', { target_lufs: -14 })}>Auto master −14</button>
      </div>
      <div className="strips">
        {project.tracks.map(t => <Strip key={t.id} t={t} run={run} lufs={levels[t.id]} selected={selection?.id === t.id} fx={fx} onOpenFx={onOpenFx} slots={slots}
          onSelect={() => setSelection({ kind: 'track', id: t.id, track: t.id })} />)}
        <div className={'strip master' + (!selection ? ' sel' : '')} onClick={() => setSelection(null)}>
          <div className="strip-name">Master</div>
          <Inserts target="master" effects={project.master.effects} fx={fx} onOpenFx={onOpenFx} slots={slots} />
          <div className="fader-wrap">
            <MasterFader value={project.master.volume_db} run={run} />
          </div>
        </div>
      </div>
      {analysis && <Measures a={analysis} />}
      {review && <div className="review">
        {review.ok ? <p className="ok">No problems found.</p> : review.warnings.map((w, i) => (
          <div key={i} className="warning"><b>{w.message}</b><small>fix: {w.fix}</small></div>))}
      </div>}
    </div>
  )
}

function MasterFader({ value, run }) {
  const [v, props] = useDrag(value, x => run('set_master', { volume_db: x }))
  return <>
    <input type="range" className="fader" min={-24} max={12} step={0.5} value={v} {...props} />
    <div className="db">{v > 0 ? '+' : ''}{v}</div>
  </>
}
