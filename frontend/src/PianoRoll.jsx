// Piano roll della clip MIDI scelta. Clic sul vuoto = nota nuova (trascina per la
// durata), trascina una nota = sposta, bordo destro = allunga, tasto destro o
// Alt+clic = cancella, Maiusc+rotella = velocity. Ogni gesto e' UN set_notes.
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icons.jsx'
import { DRUM_NAMES, isBlack, notesFromList, notesToList, pitchName, roundTo, scalePcs, snap } from './util.js'
import { Playhead } from './Widgets.jsx'

// chiave di una nota: dopo la risposta del server la selezione si ritrova
const chiave = n => `${n.pitch}|${roundTo(n.start, 4)}|${roundTo(n.length, 4)}`

const RH = 13          // altezza di una riga
const KEYS = 64        // larghezza della tastiera
const LO = 21, HI = 108

function PianoRoll({ project, clip, track, run, player, grid, setGrid, spb, onClose, height }) {
  const bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const drums = track?.instrument_type === 'drums'
  const [notes, setNotes] = useState(() => notesFromList(clip.note_list))
  const [sel, setSel] = useState(new Set())
  const [ppb, setPpb] = useState(48)
  const [drag, setDrag] = useState(null)
  const lastLen = useRef(drums ? 0.25 : 1)
  const box = useRef(null)
  const selKeys = useRef(null)     // note selezionate da ritrovare quando torna il server
  useEffect(() => {
    const list = notesFromList(clip.note_list)
    setNotes(list)
    const k = selKeys.current
    selKeys.current = null
    setSel(k ? new Set(list.map((n, i) => (k.has(chiave(n)) ? i : -1)).filter(i => i >= 0)) : new Set())
  }, [clip.id, JSON.stringify(clip.note_list)])
  const ricorda = (list, idx) => { selKeys.current = new Set([...idx].map(i => list[i] && chiave(list[i])).filter(Boolean)) }

  // larghezza visibile: righe e griglia arrivano sempre fino al bordo
  const [viewW, setViewW] = useState(800)
  useEffect(() => {
    const el = box.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setViewW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const beats = Math.max(Math.max(clip.bars * bpb, ...notes.map(n => n.start + n.length)) + bpb, Math.ceil((viewW - KEYS) / ppb))
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

  const commit = (list, keep = new Set()) => {
    setNotes(list)
    ricorda(list, keep)
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
        ricorda(cur, drag.idx)
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

  // Ctrl + rotella = zoom attorno al puntatore (listener non passivo)
  const ancora = useRef(null)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const w = e => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const px = e.clientX - r.left
      setPpb(z => {
        const nz = Math.max(12, Math.min(240, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
        ancora.current = { beat: (px + el.scrollLeft - KEYS) / z, px, z: nz }
        return nz
      })
    }
    el.addEventListener('wheel', w, { passive: false })
    return () => el.removeEventListener('wheel', w)
  }, [])
  useLayoutEffect(() => {
    const a = ancora.current
    if (!a || a.z !== ppb || !box.current) return
    ancora.current = null
    box.current.scrollLeft = Math.max(0, KEYS + a.beat * ppb - a.px)
  }, [ppb])

  const wheel = e => {
    if (!e.shiftKey) return
    const { beat, pitch } = pos(e)
    const i = notes.findIndex(n => n.pitch === pitch && beat >= n.start && beat <= n.start + n.length)
    if (i < 0) return
    e.preventDefault()
    const target = sel.has(i) ? sel : new Set([i])
    commit(notes.map((n, k) => target.has(k) ? { ...n, velocity: Math.max(1, Math.min(127, n.velocity + (e.deltaY < 0 ? 8 : -8))) } : n), sel)
  }

  const scelte = sel.size ? [...sel] : null
  const editNotes = body => {
    if (body.transpose && scelte) selKeys.current = new Set(scelte.map(i => chiave({ ...notes[i], pitch: notes[i].pitch + body.transpose })))
    run('edit_notes', { clip: clip.id, ...body, ...(scelte ? { indices: sortedIndices(notes, scelte) } : {}) })
  }
  const inizio = (clip.bar - 1) * bpb
  const toX = useCallback(t => {
    const rel = t / spb - inizio
    return rel < 0 || rel > beats ? null : KEYS + rel * ppb
  }, [spb, inizio, beats, ppb])
  const H = rows.length * RH
  const lines = useMemo(() => {
    const g = grid || 0.25
    const passo = g * ppb < 6 ? 1 : g     // linee troppo fitte: solo i beat
    return Array.from({ length: Math.ceil(beats / passo) }, (_, i) => {
      const b = i * passo
      const cls = Math.abs(b % bpb) < 1e-6 ? 'g4' : Math.abs(b % 1) < 1e-6 ? 'g1' : 'g0'
      return <line key={i} x1={b * ppb} x2={b * ppb} y1={0} y2={H} className={cls} />
    })
  }, [grid, ppb, beats, bpb, H])

  return (
    <div className="roll" style={height ? { height } : undefined}>
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
        <button className="icon-btn" title="Zoom out (Ctrl+wheel)" onClick={() => setPpb(z => Math.max(12, z / 1.4))}>−</button>
        <button className="icon-btn" title="Zoom in (Ctrl+wheel)" onClick={() => setPpb(z => Math.min(240, z * 1.4))}>+</button>
        <button className="icon-btn" title="Close (Esc)" onClick={onClose}>✕</button>
      </div>
      <div className="roll-body" ref={box} onPointerDown={down} onContextMenu={e => e.preventDefault()} onWheel={wheel}>
        <div style={{ position: 'relative', width: KEYS + W, height: rows.length * RH }}>
          {rows.map(p => (
            <div key={p} className={'roll-row' + (isBlack(p) ? ' black' : '') + (!drums && pcs.includes(p % 12) ? ' inscale' : '')}
              style={{ top: Y(p), width: KEYS + W }} />))}
          <svg className="roll-grid" style={{ left: KEYS }} width={W} height={rows.length * RH}>
            {lines}
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
          <Playhead player={player} toX={toX} height={H} />
        </div>
      </div>
      {!notes.length && <p className="roll-empty hint"><Icon name="piano" size={14} /> Click to add notes, drag to set the length.
        Or ask the assistant: “write a melody for this verse”.</p>}
    </div>
  )
}

export default memo(PianoRoll)

// indici nella forma di get_notes (note ordinate per tempo e altezza)
function sortedIndices(notes, idx) {
  const ordine = notes.map((n, i) => i).sort((a, b) => notes[a].start - notes[b].start || notes[a].pitch - notes[b].pitch)
  const pos = new Map(ordine.map((i, k) => [i, k]))
  return idx.map(i => pos.get(i))
}
