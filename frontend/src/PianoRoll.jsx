// Piano roll della clip MIDI scelta. Clic sul vuoto = nota nuova (trascina per la
// durata), trascina una nota = sposta, bordo destro = allunga, tasto destro o
// Alt+clic = cancella, Maiusc+rotella = velocity. Ogni gesto e' UN set_notes.
import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import { DRUM_NAMES, isBlack, notesFromList, notesToList, pitchName, scalePcs, snap } from './util.js'

const RH = 13          // altezza di una riga
const KEYS = 64        // larghezza della tastiera
const LO = 21, HI = 108

export default function PianoRoll({ project, clip, track, run, player, grid, setGrid, playhead, onClose }) {
  const bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const drums = track?.instrument_type === 'drums'
  const [notes, setNotes] = useState(() => notesFromList(clip.note_list))
  const [sel, setSel] = useState(new Set())
  const [ppb, setPpb] = useState(48)
  const [drag, setDrag] = useState(null)
  const lastLen = useRef(drums ? 0.25 : 1)
  const box = useRef(null)
  useEffect(() => { setNotes(notesFromList(clip.note_list)); setSel(new Set()) }, [clip.id, JSON.stringify(clip.note_list)])

  const beats = Math.max(clip.bars * bpb, ...notes.map(n => n.start + n.length)) + bpb
  const W = beats * ppb
  const pcs = useMemo(() => scalePcs(project.key, project.mode), [project.key, project.mode])
  const rows = []
  for (let p = HI; p >= LO; p--) rows.push(p)
  const Y = p => (HI - p) * RH

  // all'apertura: si scorre dove stanno le note
  useEffect(() => {
    const el = box.current
    if (!el) return
    const mid = notes.length ? notes.reduce((a, n) => a + n.pitch, 0) / notes.length : (drums ? 42 : 64)
    el.scrollTop = Y(mid) - el.clientHeight / 2
  }, [clip.id])

  const commit = list => {
    setNotes(list)
    run('set_notes', { clip: clip.id, notes: notesToList(list) })
  }

  const pos = e => {
    const r = box.current.getBoundingClientRect()
    const x = e.clientX - r.left + box.current.scrollLeft - KEYS
    const y = e.clientY - r.top + box.current.scrollTop
    return { beat: Math.max(0, x / ppb), pitch: HI - Math.floor(y / RH) }
  }

  const down = e => {
    if (e.button !== 0 && e.button !== 2) return
    const { beat, pitch } = pos(e)
    if (pitch < LO || pitch > HI) return
    const i = notes.findIndex(n => n.pitch === pitch && beat >= n.start && beat <= n.start + n.length)
    if (e.button === 2 || (e.altKey && i >= 0)) {
      e.preventDefault()
      if (i >= 0) commit(notes.filter((_, k) => k !== i))
      return
    }
    if (i >= 0) {
      const n = notes[i]
      const edge = (n.start + n.length - beat) * ppb < 7
      const nuovo = e.shiftKey ? new Set([...sel, i]) : sel.has(i) ? sel : new Set([i])
      setSel(nuovo)
      setDrag({ mode: edge ? 'resize' : 'move', x0: beat, p0: pitch, orig: notes, idx: [...nuovo], changed: false })
      if (!edge) player.audition(track.id, n.pitch, n.velocity)
      return
    }
    const start = Math.max(0, snap(beat - (grid ? grid / 2 : 0), grid))
    const n = { pitch, start, length: lastLen.current, velocity: 100 }
    const list = [...notes, n]
    setNotes(list)
    setSel(new Set([list.length - 1]))
    setDrag({ mode: 'resize', x0: start + lastLen.current, p0: pitch, orig: list, idx: [list.length - 1], changed: true })
    player.audition(track.id, pitch)
  }

  useEffect(() => {
    if (!drag) return
    const move = e => {
      const { beat, pitch } = pos(e)
      const db = beat - drag.x0
      const dp = pitch - drag.p0
      const list = drag.orig.map((n, k) => {
        if (!drag.idx.includes(k)) return n
        if (drag.mode === 'move') return { ...n, start: Math.max(0, snap(n.start + db, grid)), pitch: Math.max(0, Math.min(127, n.pitch + dp)) }
        return { ...n, length: Math.max(grid || 0.0625, snap(n.length + db, grid)) }
      })
      setNotes(list)
      drag.cur = list
      if (Math.abs(db) > 1e-3 || dp) drag.changed = true
    }
    const up = () => {
      const cur = drag.cur || drag.orig
      if (drag.changed) {
        if (drag.mode === 'resize' && drag.idx.length === 1) lastLen.current = cur[drag.idx[0]]?.length || lastLen.current
        run('set_notes', { clip: clip.id, notes: notesToList(cur) })
      }
      setDrag(null)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [drag, ppb, grid])

  useEffect(() => {
    const key = e => {
      if (e.target.closest('input, textarea, select')) return
      if ((e.key === 'Delete' || e.key === 'Backspace') && sel.size) {
        e.preventDefault()
        commit(notes.filter((_, k) => !sel.has(k)))
        setSel(new Set())
      }
      if (e.key === 'a' && (e.ctrlKey || e.metaKey) && box.current?.matches(':hover')) {
        e.preventDefault()
        setSel(new Set(notes.map((_, k) => k)))
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [sel, notes])

  const wheel = e => {
    if (!e.shiftKey) return
    const { beat, pitch } = pos(e)
    const i = notes.findIndex(n => n.pitch === pitch && beat >= n.start && beat <= n.start + n.length)
    if (i < 0) return
    e.preventDefault()
    const target = sel.has(i) ? sel : new Set([i])
    commit(notes.map((n, k) => target.has(k) ? { ...n, velocity: Math.max(1, Math.min(127, n.velocity + (e.deltaY < 0 ? 8 : -8))) } : n))
  }

  const scelte = sel.size ? [...sel] : null
  const editNotes = body => run('edit_notes', { clip: clip.id, ...body, ...(scelte ? { indices: sortedIndices(notes, scelte) } : {}) })
  const rel = playhead - (clip.bar - 1) * bpb

  return (
    <div className="roll">
      <div className="roll-bar">
        <b>{clip.name}</b><span className="hint">{track?.name} · bar {clip.bar} · {notes.length} notes{sel.size ? ` · ${sel.size} selected` : ''}</span>
        <span className="grow" />
        <label>Snap <select value={grid} onChange={e => setGrid(Number(e.target.value))}>
          {[[1, '1/4'], [0.5, '1/8'], [0.25, '1/16'], [0.125, '1/32'], [1 / 3, '1/8T'], [1 / 6, '1/16T'], [0, 'off']].map(([v, n]) =>
            <option key={n} value={v}>{n}</option>)}</select></label>
        <button title="Snap the notes to the grid" onClick={() => run('quantize', { clip: clip.id, grid: grid || 0.25 })}>Quantize</button>
        <button title="Small timing and velocity changes" onClick={() => run('humanize', { clip: clip.id })}>Humanize</button>
        <button title="Each note lasts until the next" onClick={() => editNotes({ legato: true })}>Legato</button>
        <button title="Octave down" onClick={() => editNotes({ transpose: -12 })}>-12</button>
        <button title="Semitone down" onClick={() => editNotes({ transpose: -1 })}>-1</button>
        <button title="Semitone up" onClick={() => editNotes({ transpose: 1 })}>+1</button>
        <button title="Octave up" onClick={() => editNotes({ transpose: 12 })}>+12</button>
        <button title="Notes outside the scale go to the nearest scale note" onClick={() => run('fit_to_scale', { target: clip.id })}>Fit to scale</button>
        <button className="icon-btn" title="Zoom out" onClick={() => setPpb(z => Math.max(12, z / 1.4))}>−</button>
        <button className="icon-btn" title="Zoom in" onClick={() => setPpb(z => Math.min(240, z * 1.4))}>+</button>
        <button className="icon-btn" title="Close" onClick={onClose}>✕</button>
      </div>
      <div className="roll-body" ref={box} onPointerDown={down} onContextMenu={e => e.preventDefault()} onWheel={wheel}>
        <div style={{ position: 'relative', width: KEYS + W, height: rows.length * RH }}>
          {rows.map(p => (
            <div key={p} className={'roll-row' + (isBlack(p) ? ' black' : '') + (!drums && pcs.includes(p % 12) ? ' inscale' : '')}
              style={{ top: Y(p), width: KEYS + W }} />))}
          <svg className="roll-grid" style={{ left: KEYS }} width={W} height={rows.length * RH}>
            {Array.from({ length: Math.ceil(beats / (grid || 0.25)) }, (_, i) => {
              const b = i * (grid || 0.25)
              const cls = Math.abs(b % bpb) < 1e-6 ? 'g4' : Math.abs(b % 1) < 1e-6 ? 'g1' : 'g0'
              return <line key={i} x1={b * ppb} x2={b * ppb} y1={0} y2={rows.length * RH} className={cls} />
            })}
            <rect x={clip.bars * bpb * ppb} y={0} width={Math.max(0, W - clip.bars * bpb * ppb)} height={rows.length * RH} className="past-end" />
          </svg>
          <div className="keys">
            {rows.map(p => (
              <div key={p} className={'key' + (isBlack(p) ? ' black' : '') + (p % 12 === 0 ? ' c' : '')} style={{ top: Y(p), height: RH }}
                onPointerDown={e => { e.stopPropagation(); player.audition(track.id, p) }}>
                {drums ? (DRUM_NAMES[p] || '') : (p % 12 === 0 ? pitchName(p) : '')}
              </div>))}
          </div>
          {notes.map((n, k) => (
            <div key={k} className={'note' + (sel.has(k) ? ' sel' : '')}
              style={{ left: KEYS + n.start * ppb, top: Y(n.pitch) + 1, width: Math.max(3, n.length * ppb - 1), height: RH - 2,
                opacity: 0.45 + 0.55 * n.velocity / 127, '--c': track?.color }}
              title={`${pitchName(n.pitch)} · start ${n.start} · length ${n.length} · velocity ${n.velocity}`} />))}
          {rel >= 0 && rel <= beats && <div className="playhead" style={{ left: KEYS + rel * ppb, height: rows.length * RH }} />}
        </div>
      </div>
      {!notes.length && <p className="roll-empty hint"><Icon name="piano" size={14} /> Click to add notes, drag to set the length.
        Or ask the assistant: “write a melody for this verse”.</p>}
    </div>
  )
}

// indici nella forma di get_notes (note ordinate per tempo e altezza)
function sortedIndices(notes, idx) {
  const ordine = notes.map((n, i) => i).sort((a, b) => notes[a].start - notes[b].start || notes[a].pitch - notes[b].pitch)
  const pos = new Map(ordine.map((i, k) => [i, k]))
  return idx.map(i => pos.get(i))
}
