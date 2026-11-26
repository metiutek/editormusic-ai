// Arrangiamento: righello (clic = vai li', trascina = loop), sezioni, tracce con le
// clip. Trascinare sposta (anche su un'altra traccia), il bordo destro allunga.
// Ogni gesto finisce in UNA operazione di Store (set_clip, add_clip...).
import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import { notesFromList, snap } from './util.js'

const HEAD = 190
const ROW = 58
const RULER = 22
const SECT = 22

const picchi = new Map()   // asset -> {per_second, peaks}
function usePeaks(asset) {
  const [p, setP] = useState(() => picchi.get(asset) || null)
  useEffect(() => {
    if (!asset || picchi.has(asset)) return
    let vivo = true
    api(`/api/peaks/${asset}`).then(r => { picchi.set(asset, r); if (vivo) setP(r) }).catch(() => {})
    return () => { vivo = false }
  }, [asset])
  return p
}

function Waveform({ clip, w, h }) {
  const pk = usePeaks(clip.asset)
  if (!pk || w < 4) return null
  const durata = clip._seconds
  const i0 = Math.floor((clip.offset_s || 0) * pk.per_second)
  const n = Math.max(1, Math.floor(durata * pk.per_second * 2 ** (-(clip.transpose || 0) / 12)))
  const cols = Math.max(1, Math.floor(w))
  const pts = []
  for (let x = 0; x < cols; x++) {
    const a = i0 + Math.floor(x / cols * n), b = i0 + Math.floor((x + 1) / cols * n)
    let m = 0
    for (let k = a; k <= b && k < pk.peaks.length; k++) m = Math.max(m, pk.peaks[k])
    pts.push([x, m])
  }
  const mid = h / 2
  const d = pts.map(([x, m]) => `M${x} ${mid - m * mid}V${mid + m * mid}`).join('')
  return <svg className="wave" width={w} height={h}><path d={d} /></svg>
}

function MiniNotes({ clip, w, h }) {
  const notes = notesFromList(clip.note_list)
  if (!notes.length) return null
  const lo = Math.min(...notes.map(n => n.pitch)), hi = Math.max(...notes.map(n => n.pitch))
  const span = Math.max(12, hi - lo + 1)
  const L = clip.loop_bars ? clip.loop_bars * clip._bpb : clip.bars * clip._bpb
  const rip = clip.loop_bars ? Math.ceil(clip.bars / clip.loop_bars) : 1
  const total = clip.bars * clip._bpb
  const sx = w / total
  const rects = []
  for (let k = 0; k < rip; k++) {
    for (const n of notes) {
      if (clip.loop_bars && n.start >= L) continue
      const s = k * L + n.start
      if (s >= total) continue
      const y = h - 4 - ((n.pitch - lo + (span - (hi - lo + 1)) / 2) / span) * (h - 10)
      rects.push(<rect key={k + ':' + rects.length} x={s * sx} y={y - 1.5} width={Math.max(1.5, Math.min(n.length, total - s) * sx - 0.5)} height={3} />)
    }
  }
  return <svg className="mininotes" width={w} height={h}>{rects}</svg>
}

export default function Arrange({ project, ppb, selection, setSelection, run, playhead, onSeek, loop, setLoop, grid,
  onOpenClip, onAddTrack }) {
  const bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const ref = useRef(null)
  const [drag, setDrag] = useState(null)
  const [ghost, setGhost] = useState(null)
  const [loopDrag, setLoopDrag] = useState(null)
  const bars = Math.max(32, Math.ceil(project.bars) + 8)
  const W = bars * bpb * ppb
  const X = beat => HEAD + beat * ppb
  const tracks = project.tracks

  const beatFromEvent = e => {
    const r = ref.current.getBoundingClientRect()
    return Math.max(0, (e.clientX - r.left + ref.current.scrollLeft - HEAD) / ppb)
  }
  const rowFromEvent = e => {
    const r = ref.current.getBoundingClientRect()
    return Math.floor((e.clientY - r.top + ref.current.scrollTop - RULER - SECT) / ROW)
  }

  useEffect(() => {
    if (!drag && !loopDrag) return
    const move = e => {
      if (loopDrag) { setLoopDrag(d => ({ ...d, b: beatFromEvent(e) })); return }
      const db = (e.clientX - drag.x0) / ppb
      if (drag.mode === 'move') {
        const start = Math.max(0, snap(drag.start + db, grid || 0))
        const row = Math.max(0, Math.min(tracks.length - 1, rowFromEvent(e)))
        setGhost({ id: drag.clip.id, start, len: drag.len, row })
      } else {
        const len = Math.max(grid || 0.25, snap(drag.len + db, grid || 0))
        setGhost({ id: drag.clip.id, start: drag.start, len, row: drag.row })
      }
    }
    const up = () => {
      if (loopDrag) {
        const a = Math.min(loopDrag.a, loopDrag.b), b = Math.max(loopDrag.a, loopDrag.b)
        if (b - a < 0.5) onSeek(snap(loopDrag.a, 0))
        else setLoop([snap(a, bpb), Math.max(snap(b, bpb), snap(a, bpb) + bpb)])
        setLoopDrag(null)
        return
      }
      const g = ghost
      setDrag(null); setGhost(null)
      if (!g) return
      const body = { clip: drag.clip.id }
      if (Math.abs(g.start - drag.start) > 1e-6) body.bar = g.start / bpb + 1
      if (Math.abs(g.len - drag.len) > 1e-6) body.bars = g.len / bpb
      if (g.row !== drag.row) body.track = tracks[g.row].id
      if (Object.keys(body).length > 1) run('set_clip', body)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [drag, ghost, loopDrag, ppb, grid])

  // segue il cursore di riproduzione
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const x = X(playhead)
    if (x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - HEAD - 40
  }, [Math.floor(playhead / bpb)])

  const startDrag = (e, t, c, row, mode) => {
    e.stopPropagation()
    if (e.button !== 0) return
    setSelection({ kind: 'clip', id: c.id, track: t.id })
    setDrag({ mode, clip: c, x0: e.clientX, start: (c.bar - 1) * bpb, len: c.bars * bpb, row })
  }

  const loopBox = loopDrag ? [Math.min(loopDrag.a, loopDrag.b), Math.max(loopDrag.a, loopDrag.b)] : loop

  return (
    <div className="arrange" ref={ref}>
      <div className="arr-inner" style={{ width: HEAD + W, height: RULER + SECT + tracks.length * ROW + 60 }}>
        {/* righello */}
        <div className="ruler" style={{ width: HEAD + W }}
          onPointerDown={e => { if (e.button === 0) setLoopDrag({ a: beatFromEvent(e), b: beatFromEvent(e) }) }}>
          <div className="corner" style={{ width: HEAD }} />
          {Array.from({ length: bars }, (_, i) => (
            <div key={i} className={'bar-num' + (i % 4 === 0 ? ' four' : '')} style={{ left: X(i * bpb) }}>{i + 1}</div>))}
          {loopBox && <div className="loop-box" style={{ left: X(loopBox[0]), width: (loopBox[1] - loopBox[0]) * ppb }} />}
        </div>
        {/* sezioni */}
        <div className="sections" style={{ top: RULER, width: HEAD + W }}>
          <div className="corner" style={{ width: HEAD }}><span className="hint">Sections</span></div>
          {project.sections.map(s => (
            <div key={s.id} className={'section' + (selection?.id === s.id ? ' sel' : '')}
              style={{ left: X((s.bar - 1) * bpb), width: s.bars * bpb * ppb, background: s.color || '#555a70' }}
              title={s.lyrics || s.name}
              onClick={() => setSelection({ kind: 'section', id: s.id })}
              onDoubleClick={() => onSeek((s.bar - 1) * bpb)}>{s.name}</div>))}
        </div>
        {/* griglia */}
        <svg className="grid" style={{ left: HEAD, top: RULER + SECT }} width={W} height={tracks.length * ROW + 60}>
          {Array.from({ length: bars * bpb }, (_, i) => (
            <line key={i} x1={i * ppb} x2={i * ppb} y1={0} y2={tracks.length * ROW + 60}
              className={i % (bpb * 4) === 0 ? 'g4' : i % bpb === 0 ? 'g1' : 'g0'} />))}
        </svg>
        {/* tracce */}
        {tracks.map((t, row) => (
          <div key={t.id} className={'track-row' + (selection?.track === t.id || selection?.id === t.id ? ' sel' : '')}
            style={{ top: RULER + SECT + row * ROW, width: HEAD + W }}
            onDoubleClick={e => {
              if (t.kind !== 'midi' || e.target.closest('.clip') || e.target.closest('.track-head')) return
              const bar = Math.floor(beatFromEvent(e) / bpb) + 1
              run('add_clip', { track: t.id, bar, bars: 1 })
            }}>
            <div className="track-head" style={{ width: HEAD, borderLeftColor: t.color }}
              onClick={() => setSelection({ kind: 'track', id: t.id, track: t.id })}>
              <div className="th-top">
                <span className="th-name" title={t.name}>{t.name}</span>
                <button className={'ms' + (t.mute ? ' on' : '')} title="Mute" onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, mute: !t.mute }) }}>M</button>
                <button className={'ms solo' + (t.solo ? ' on' : '')} title="Solo" onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, solo: !t.solo }) }}>S</button>
              </div>
              <div className="th-sub">
                <Icon name={t.kind === 'audio' ? 'wave' : t.kind === 'bus' ? 'sliders' : t.instrument_type === 'drums' ? 'drum' : 'piano'} size={12} />
                <span>{t.kind === 'midi' ? t.instrument : t.kind}</span>
                <span className="grow" />
                <span className="db">{t.volume_db > 0 ? '+' : ''}{t.volume_db} dB</span>
              </div>
            </div>
            {t.kind !== 'bus' && t.clips.map(c => {
              const g = ghost && ghost.id === c.id ? ghost : null
              if (g && g.row !== row) return null
              const start = g ? g.start : (c.bar - 1) * bpb
              const len = g ? g.len : c.bars * bpb
              const w = len * ppb
              const cc = { ...c, _bpb: bpb, _seconds: len * 60 / project.bpm, bars: len / bpb }
              return (
                <div key={c.id} className={'clip' + (selection?.id === c.id ? ' sel' : '') + (c.muted ? ' muted' : '')}
                  style={{ left: X(start), width: Math.max(4, w), '--c': t.color }}
                  onPointerDown={e => startDrag(e, t, c, row, 'move')}
                  onDoubleClick={e => { e.stopPropagation(); onOpenClip(c.id) }}>
                  <span className="clip-name">{c.name}</span>
                  {t.kind === 'midi' ? <MiniNotes clip={cc} w={w} h={ROW - 8} /> : <Waveform clip={cc} w={w} h={ROW - 8} />}
                  <div className="resize" onPointerDown={e => startDrag(e, t, c, row, 'resize')} />
                </div>)
            })}
            {ghost && ghost.row === row && !t.clips.some(c => c.id === ghost.id) && (
              <div className="clip ghost" style={{ left: X(ghost.start), width: ghost.len * ppb, '--c': t.color }} />)}
          </div>))}
        <div className="add-track" style={{ top: RULER + SECT + tracks.length * ROW + 8, width: HEAD - 10 }}>
          <button onClick={() => onAddTrack('midi')}><Icon name="plus" size={13} /> MIDI</button>
          <button onClick={() => onAddTrack('audio')}><Icon name="plus" size={13} /> Audio</button>
          <button onClick={() => onAddTrack('bus')}><Icon name="plus" size={13} /> Bus</button>
        </div>
        <div className="playhead" style={{ left: X(playhead), height: RULER + SECT + tracks.length * ROW + 40 }} />
      </div>
    </div>
  )
}

export { HEAD }
