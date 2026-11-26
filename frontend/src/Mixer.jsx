// Mixer: un canale per traccia (volume, pan, mute, solo, misura), il master,
// e i pulsanti che misurano e sistemano: balance mix, review, auto master.
import { useState } from 'react'
import { api } from './api.js'
import { Measures } from './Inspector.jsx'

function Strip({ t, run, lufs, selected, onSelect }) {
  const [v, setV] = useState(null)
  const vol = v ?? t.volume_db
  return (
    <div className={'strip' + (selected ? ' sel' : '')} onClick={onSelect} style={{ '--c': t.color }}>
      <div className="strip-name" title={t.name}>{t.name}</div>
      <input type="range" className="pan" min={-1} max={1} step={0.05} defaultValue={t.pan || 0} key={'p' + t.pan}
        title={`pan ${t.pan || 0}`} onPointerUp={e => run('set_track', { track: t.id, pan: Number(e.target.value) })} />
      <div className="fader-wrap">
        <input type="range" className="fader" min={-60} max={12} step={0.5} value={vol}
          onChange={e => setV(Number(e.target.value))}
          onPointerUp={() => { if (v !== null) { run('set_track', { track: t.id, volume_db: v }); setV(null) } }} />
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

export default function Mixer({ project, run, selection, setSelection, analysis, onAnalyze }) {
  const [levels, setLevels] = useState({})
  const [review, setReview] = useState(null)
  const [busy, setBusy] = useState('')
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
        {project.tracks.map(t => <Strip key={t.id} t={t} run={run} lufs={levels[t.id]} selected={selection?.id === t.id}
          onSelect={() => setSelection({ kind: 'track', id: t.id, track: t.id })} />)}
        <div className={'strip master' + (!selection ? ' sel' : '')} onClick={() => setSelection(null)}>
          <div className="strip-name">Master</div>
          <div className="fader-wrap">
            <input type="range" className="fader" min={-24} max={12} step={0.5} defaultValue={project.master.volume_db} key={project.master.volume_db}
              onPointerUp={e => run('set_master', { volume_db: Number(e.target.value) })} />
          </div>
          <div className="db">{project.master.volume_db}</div>
          <div className="hint">{project.master.effects.map(e => e.type).join(' → ') || 'no effects'}</div>
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
