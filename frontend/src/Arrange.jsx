// Arrangiamento: righello (clic = vai li', trascina = loop), sezioni, tracce con le
// clip. Trascinare sposta (anche su un'altra traccia), il bordo destro allunga.
// Ogni gesto finisce in UNA operazione di Store (set_clip, add_clip...).
// Doppio clic sul nome (o F2) rinomina; tasto destro apre il menu.
// Il cursore si muove fuori da React (Playhead): suonare non ridisegna le tracce.
import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import Splitter from './Splitter.jsx'
import { notesFromList, snap } from './util.js'
import { ContextMenu, InlineEdit, Playhead } from './Widgets.jsx'

const HEAD_DEFAULT = 190
const ROW = 58
const RULER = 22
const SECT = 22
const MAX_COLS = 3000   // colonne massime di una forma d'onda (oltre si allarga l'SVG)

const picchi = new Map()   // asset -> {per_second, peaks}
function usePeaks(asset) {
  const [p, setP] = useState(() => picchi.get(asset) || null)
  useEffect(() => {
    if (!asset) return
    if (picchi.has(asset)) { setP(picchi.get(asset)); return }
    let vivo = true
    api(`/api/peaks/${asset}`).then(r => { picchi.set(asset, r); if (vivo) setP(r) }).catch(() => {})
    return () => { vivo = false }
  }, [asset])
  return p
}

function Waveform({ clip, seconds, w, h }) {
  const pk = usePeaks(clip.asset)
  const cols = Math.max(1, Math.min(MAX_COLS, Math.floor(w)))
  const d = useMemo(() => {
    if (!pk || w < 4) return ''
    const i0 = Math.floor((clip.offset_s || 0) * pk.per_second)
    const n = Math.max(1, Math.floor(seconds * pk.per_second * 2 ** (-(clip.transpose || 0) / 12)))
    const mid = h / 2
    let out = ''
    for (let x = 0; x < cols; x++) {
      const a = i0 + Math.floor(x / cols * n), b = i0 + Math.floor((x + 1) / cols * n)
      let m = 0
      for (let k = a; k <= b && k < pk.peaks.length; k++) if (pk.peaks[k] > m) m = pk.peaks[k]
      if (m > 0.002) out += `M${x} ${(mid - m * mid).toFixed(1)}V${(mid + m * mid).toFixed(1)}`
    }
    return out
  }, [pk, cols, h, seconds, clip.offset_s, clip.transpose])
  if (!d) return null
  return <svg className="wave" width={w} height={h} viewBox={`0 0 ${cols} ${h}`} preserveAspectRatio="none"><path d={d} vectorEffect="non-scaling-stroke" /></svg>
}

function MiniNotes({ clip, bpb, bars, w, h }) {
  const rects = useMemo(() => {
    const notes = notesFromList(clip.note_list)
    if (!notes.length) return []
    const lo = Math.min(...notes.map(n => n.pitch)), hi = Math.max(...notes.map(n => n.pitch))
    const span = Math.max(12, hi - lo + 1)
    const L = clip.loop_bars ? clip.loop_bars * bpb : bars * bpb
    const rip = clip.loop_bars ? Math.ceil(bars / clip.loop_bars) : 1
    const total = bars * bpb
    const out = []
    for (let k = 0; k < rip; k++) {
      for (const n of notes) {
        if (clip.loop_bars && n.start >= L) continue
        const s = k * L + n.start
        if (s >= total) continue
        const y = 1 - (n.pitch - lo + (span - (hi - lo + 1)) / 2) / span
        out.push([s / total, y, Math.min(n.length, total - s) / total])
      }
    }
    return out
  }, [clip.note_list, clip.loop_bars, bars, bpb])
  if (!rects.length) return null
  return (
    <svg className="mininotes" width={w} height={h}>
      {rects.map(([x, y, l], i) => <rect key={i} x={x * w} y={4 + y * (h - 12)} width={Math.max(1.5, l * w - 0.5)} height={3} />)}
    </svg>)
}

// Una clip. memo: trascinarne una non ridisegna le altre.
const ClipView = memo(function ClipView({ c, t, row, start, len, ppb, bpb, bpm, selected, editing, pending, onDown, onOpen, onMenu, onRename, onStopEdit }) {
  const w = len * ppb
  return (
    <div className={'clip' + (selected ? ' sel' : '') + (c.muted ? ' muted' : '') + (pending ? ' pending' : '')}
      style={{ left: HEAD_PLACEHOLDER, transform: `translateX(${start * ppb}px)`, width: Math.max(4, w), '--c': t.color }}
      onPointerDown={e => onDown(e, t, c, row, 'move')}
      onDoubleClick={e => { e.stopPropagation(); onOpen(c.id) }}
      onContextMenu={e => onMenu(e, t, c)}
      title={c.name}>
      {editing
        ? <InlineEdit className="clip-edit" value={c.name} onCommit={v => onRename(c.id, v)} onCancel={onStopEdit} />
        : <span className="clip-name">{c.name}</span>}
      {t.kind === 'midi'
        ? <MiniNotes clip={c} bpb={bpb} bars={len / bpb} w={w} h={ROW - 8} />
        : <Waveform clip={c} seconds={len * 60 / bpm} w={w} h={ROW - 12} />}
      <div className="resize" onPointerDown={e => onDown(e, t, c, row, 'resize')} />
    </div>)
})
const HEAD_PLACEHOLDER = 'var(--head)'

function Arrange({ project, ppb, setPpb, selection, setSelection, run, player, spb, onSeek, loop, setLoop, grid,
  onOpenClip, onAddTrack, head = HEAD_DEFAULT, onHead }) {
  const HEAD = head
  const bpb = (project.time_sig[0] * 4) / project.time_sig[1]
  const ref = useRef(null)
  const [drag, setDrag] = useState(null)
  const [ghost, setGhost] = useState(null)
  const [loopDrag, setLoopDrag] = useState(null)
  const [editing, setEditing] = useState(null)      // {kind: track|clip|section, id}
  const [menu, setMenu] = useState(null)
  const [viewH, setViewH] = useState(400)
  const bars = Math.max(32, Math.ceil(project.bars) + 8)
  const W = bars * bpb * ppb
  const X = beat => HEAD + beat * ppb
  const tracks = project.tracks
  const contentH = Math.max(viewH, RULER + SECT + tracks.length * ROW + 60)

  // altezza visibile: la griglia riempie sempre la finestra
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setViewH(el.clientHeight))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

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
      if (Math.abs(e.clientX - drag.x0) < 3 && Math.abs(e.clientY - drag.y0) < 3 && !ghost) return
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
      const d = drag
      setDrag(null)
      if (!g) return
      const body = { clip: d.clip.id }
      if (Math.abs(g.start - d.start) > 1e-6) body.bar = g.start / bpb + 1
      if (Math.abs(g.len - d.len) > 1e-6) body.bars = g.len / bpb
      if (g.row !== d.row && tracks[g.row]) body.track = tracks[g.row].id
      if (Object.keys(body).length > 1) {
        // la clip resta dove e' stata lasciata finche' il server non risponde: niente salto indietro
        setGhost({ ...g, pending: true })
        Promise.resolve(run('set_clip', body)).finally(() => setGhost(x => (x && x.pending && x.id === g.id ? null : x)))
      } else setGhost(null)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [drag, ghost, loopDrag, ppb, grid, HEAD])

  // segue il cursore mentre suona (anche quando il loop torna indietro)
  const segui = useRef({})
  segui.current = { HEAD, ppb, spb, drag: !!drag || !!loopDrag }
  useEffect(() => player.onFrame((t, playing) => {
    const el = ref.current
    const s = segui.current
    if (!el || !playing || s.drag) return
    const x = s.HEAD + (t / s.spb) * s.ppb
    if (x > el.scrollLeft + el.clientWidth - 30 || x < el.scrollLeft + s.HEAD) el.scrollLeft = x - s.HEAD - 30
  }), [player])

  // Ctrl + rotella = zoom attorno al puntatore
  const ancora = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const wheel = e => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const px = e.clientX - r.left
      setPpb(z => {
        const nz = Math.max(2, Math.min(200, z * (e.deltaY < 0 ? 1.15 : 1 / 1.15)))
        ancora.current = { beat: (px + el.scrollLeft - segui.current.HEAD) / z, px, z: nz }
        return nz
      })
    }
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  }, [setPpb])
  useLayoutEffect(() => {
    const a = ancora.current
    if (!a || a.z !== ppb) return
    ancora.current = null
    ref.current.scrollLeft = Math.max(0, HEAD + a.beat * ppb - a.px)
  }, [ppb])

  // F2 = rinomina cio' che e' selezionato
  useEffect(() => {
    const key = e => {
      if (e.key !== 'F2' || !selection || e.target.closest('input, textarea, select')) return
      e.preventDefault()
      setEditing({ kind: selection.kind, id: selection.id })
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [selection])

  const startDrag = useCallback((e, t, c, row, mode) => {
    e.stopPropagation()
    if (e.button !== 0) return
    setSelection({ kind: 'clip', id: c.id, track: t.id })
    setDrag({ mode, clip: c, x0: e.clientX, y0: e.clientY, start: (c.bar - 1) * bpb, len: c.bars * bpb, row })
  }, [bpb, setSelection])

  const stopEdit = useCallback(() => setEditing(null), [])
  const renameClip = useCallback((id, name) => { setEditing(null); run('set_clip', { clip: id, name }) }, [run])
  const renameTrack = (id, name) => { setEditing(null); run('set_track', { track: id, name }) }
  const renameSection = (id, name) => { setEditing(null); run('set_section', { section: id, name }) }

  const posBar = () => player.position() / spb / bpb + 1

  const clipMenu = useCallback((e, t, c) => {
    e.preventDefault(); e.stopPropagation()
    setSelection({ kind: 'clip', id: c.id, track: t.id })
    const at = posBar()
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: 'Rename', icon: 'text', hint: 'F2', onClick: () => setEditing({ kind: 'clip', id: c.id }) },
      t.kind === 'midi' && { label: 'Edit notes', icon: 'piano', onClick: () => onOpenClip(c.id) },
      { label: 'Duplicate', icon: 'copy', hint: 'Ctrl+D', onClick: () => run('duplicate_clip', { clip: c.id }) },
      { label: 'Split at playhead', icon: 'scissors', disabled: !(at > c.bar && at < c.bar + c.bars), onClick: () => run('split_clip', { clip: c.id, at_bar: at }) },
      { label: c.muted ? 'Unmute clip' : 'Mute clip', icon: 'eyeOff', onClick: () => run('set_clip', { clip: c.id, muted: !c.muted }) },
      '-',
      { label: 'Delete', icon: 'trash', hint: 'Del', danger: true, onClick: () => { run('remove_clip', { clip: c.id }); setSelection(null) } },
    ] })
  }, [run, setSelection, onOpenClip, spb, bpb])

  const trackMenu = (e, t) => {
    e.preventDefault(); e.stopPropagation()
    setSelection({ kind: 'track', id: t.id, track: t.id })
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: 'Rename', icon: 'text', hint: 'F2', onClick: () => setEditing({ kind: 'track', id: t.id }) },
      t.kind === 'midi' && { label: 'Add clip at playhead', icon: 'plus', onClick: () => run('add_clip', { track: t.id, bar: Math.floor(posBar()), bars: bpb === 4 ? 4 : 1 }) },
      { label: t.mute ? 'Unmute' : 'Mute', icon: 'eyeOff', onClick: () => run('set_track', { track: t.id, mute: !t.mute }) },
      { label: t.solo ? 'Unsolo' : 'Solo', icon: 'eye', onClick: () => run('set_track', { track: t.id, solo: !t.solo }) },
      { label: 'Duplicate track', icon: 'copy', onClick: () => run('duplicate_track', { track: t.id }) },
      '-',
      { label: 'Delete track', icon: 'trash', danger: true, onClick: () => { run('remove_track', { track: t.id }); setSelection(null) } },
    ] })
  }

  const sectionMenu = (e, s) => {
    e.preventDefault(); e.stopPropagation()
    setSelection({ kind: 'section', id: s.id })
    setMenu({ x: e.clientX, y: e.clientY, items: [
      { label: 'Rename', icon: 'text', hint: 'F2', onClick: () => setEditing({ kind: 'section', id: s.id }) },
      { label: 'Play from here', icon: 'play', onClick: () => onSeek((s.bar - 1) * bpb) },
      { label: 'Loop this section', icon: 'loop', onClick: () => setLoop([(s.bar - 1) * bpb, (s.bar - 1 + s.bars) * bpb]) },
      '-',
      { label: 'Remove marker', icon: 'trash', danger: true, onClick: () => { run('remove_section', { section: s.id }); setSelection(null) } },
    ] })
  }

  // traccia nuova: selezionata e col nome gia' pronto da scrivere
  const nuova = async kind => {
    const r = await onAddTrack(kind)
    const id = r?.result?.id
    if (!id) return
    setSelection({ kind: 'track', id, track: id })
    setEditing({ kind: 'track', id })
    requestAnimationFrame(() => { const el = ref.current; if (el) el.scrollTop = el.scrollHeight })
  }

  const loopBox = loopDrag ? [Math.min(loopDrag.a, loopDrag.b), Math.max(loopDrag.a, loopDrag.b)] : loop
  const toX = useCallback(t => HEAD + (t / spb) * ppb, [HEAD, spb, ppb])
  const toXruler = useCallback(t => HEAD + (t / spb) * ppb - 5, [HEAD, spb, ppb])

  // griglia disegnata dal CSS: costo zero anche con centinaia di battute
  const gridBg = useMemo(() => {
    const lay = [`linear-gradient(to right, #ffffff2a 1px, transparent 1px) 0 0 / ${4 * bpb * ppb}px 100%`,
      `linear-gradient(to right, #ffffff12 1px, transparent 1px) 0 0 / ${bpb * ppb}px 100%`]
    if (ppb >= 10) lay.push(`linear-gradient(to right, #ffffff07 1px, transparent 1px) 0 0 / ${ppb}px 100%`)
    return lay.join(',')
  }, [bpb, ppb])
  const step = ppb * bpb < 18 ? 8 : ppb * bpb < 36 ? 4 : ppb * bpb < 60 ? 2 : 1   // numeri del righello leggibili

  return (
    <div className="arrange" ref={ref} style={{ '--head': HEAD + 'px' }}
      onPointerDown={e => { if (e.button === 0 && (e.target === e.currentTarget || e.target.classList.contains('arr-inner') || e.target.classList.contains('lanes-bg'))) setSelection(null) }}>
      <div className="arr-inner" style={{ width: HEAD + W, height: contentH }}>
        {/* righello */}
        <div className="ruler" style={{ width: HEAD + W }} title="Click: move the playhead · drag: set the loop"
          onPointerDown={e => { if (e.button === 0 && !e.target.closest('.corner')) setLoopDrag({ a: beatFromEvent(e), b: beatFromEvent(e) }) }}>
          <div className="corner" style={{ width: HEAD }} />
          {Array.from({ length: Math.ceil(bars / step) }, (_, k) => {
            const i = k * step
            return <div key={i} className={'bar-num' + (i % 4 === 0 ? ' four' : '')} style={{ left: X(i * bpb) }}>{i + 1}</div>
          })}
          {loopBox && <div className="loop-box" style={{ left: X(loopBox[0]), width: (loopBox[1] - loopBox[0]) * ppb }} />}
          <Playhead player={player} toX={toXruler} className="ph-mark" />
        </div>
        {/* sezioni */}
        <div className="sections" style={{ top: RULER, width: HEAD + W }}>
          <div className="corner" style={{ width: HEAD }}><span className="hint">Sections</span>
            {onHead && <Splitter dir="x" value={HEAD} onChange={onHead} onReset={() => onHead(HEAD_DEFAULT)}
              title="Drag to resize the track names · double-click to reset" />}</div>
          {project.sections.map(s => (
            <div key={s.id} className={'section' + (selection?.id === s.id ? ' sel' : '')}
              style={{ left: X((s.bar - 1) * bpb), width: s.bars * bpb * ppb, background: s.color || '#555a70' }}
              title={(s.lyrics || s.name) + '\nDouble-click to rename · right-click for more'}
              onClick={() => setSelection({ kind: 'section', id: s.id })}
              onDoubleClick={() => setEditing({ kind: 'section', id: s.id })}
              onContextMenu={e => sectionMenu(e, s)}>
              {editing?.kind === 'section' && editing.id === s.id
                ? <InlineEdit value={s.name} onCommit={v => renameSection(s.id, v)} onCancel={stopEdit} />
                : s.name}</div>))}
        </div>
        {/* griglia */}
        <div className="lanes-bg" style={{ left: HEAD, top: RULER + SECT, width: W, height: contentH - RULER - SECT, background: gridBg }} />
        {/* tracce */}
        {tracks.map((t, row) => (
          <div key={t.id} className={'track-row' + (selection?.track === t.id || selection?.id === t.id ? ' sel' : '')}
            style={{ top: RULER + SECT + row * ROW, width: HEAD + W }}
            onPointerDown={e => { if (e.button === 0 && e.target === e.currentTarget) setSelection({ kind: 'track', id: t.id, track: t.id }) }}
            onContextMenu={e => { if (e.target === e.currentTarget) trackMenu(e, t) }}
            onDoubleClick={e => {
              if (t.kind !== 'midi' || e.target !== e.currentTarget) return
              const bar = Math.floor(beatFromEvent(e) / bpb) + 1
              // clip nuova: selezionata e subito aperta nel piano roll
              Promise.resolve(run('add_clip', { track: t.id, bar, bars: 1 })).then(r => {
                const id = r?.result?.id
                if (id) { setSelection({ kind: 'clip', id, track: t.id }); onOpenClip(id) }
              })
            }}>
            <div className="track-head" style={{ width: HEAD, borderLeftColor: t.color }}
              onPointerDown={() => setSelection({ kind: 'track', id: t.id, track: t.id })}
              onContextMenu={e => trackMenu(e, t)}>
              <div className="th-top">
                {editing?.kind === 'track' && editing.id === t.id
                  ? <InlineEdit className="th-edit" value={t.name} onCommit={v => renameTrack(t.id, v)} onCancel={stopEdit} />
                  : <span className="th-name" title={t.name + '\nDouble-click to rename'}
                    onDoubleClick={e => { e.stopPropagation(); setEditing({ kind: 'track', id: t.id }) }}>{t.name}</span>}
                <button className={'ms' + (t.mute ? ' on' : '')} title="Mute" onPointerDown={e => e.stopPropagation()}
                  onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, mute: !t.mute }) }}>M</button>
                <button className={'ms solo' + (t.solo ? ' on' : '')} title="Solo" onPointerDown={e => e.stopPropagation()}
                  onClick={e => { e.stopPropagation(); run('set_track', { track: t.id, solo: !t.solo }) }}>S</button>
              </div>
              <div className="th-sub">
                <Icon name={t.kind === 'audio' ? 'wave' : t.kind === 'bus' ? 'sliders' : t.instrument_type === 'drums' ? 'drum' : 'piano'} size={12} />
                <span className="th-inst">{t.kind === 'midi' ? t.instrument : t.kind}</span>
                <span className="grow" />
                <span className="db">{t.volume_db > 0 ? '+' : ''}{t.volume_db} dB</span>
              </div>
            </div>
            {t.kind !== 'bus' && t.clips.map(c => {
              const g = ghost && ghost.id === c.id ? ghost : null
              if (g && g.row !== row) return null
              return <ClipView key={c.id} c={c} t={t} row={row}
                start={g ? g.start : (c.bar - 1) * bpb} len={g ? g.len : c.bars * bpb}
                ppb={ppb} bpb={bpb} bpm={project.bpm} selected={selection?.id === c.id} pending={!!g?.pending}
                editing={editing?.kind === 'clip' && editing.id === c.id}
                onDown={startDrag} onOpen={onOpenClip} onMenu={clipMenu} onRename={renameClip} onStopEdit={stopEdit} />
            })}
            {ghost && ghost.row === row && !t.clips.some(c => c.id === ghost.id) && (
              <div className={'clip' + (ghost.pending ? '' : ' ghost')} style={{ left: X(ghost.start), width: ghost.len * ppb, '--c': t.color }} />)}
          </div>))}
        <div className="add-track" style={{ top: RULER + SECT + tracks.length * ROW + 8, width: HEAD - 10 }}>
          <button title="New track with an instrument" onClick={() => nuova('midi')}><Icon name="plus" size={13} /> MIDI</button>
          <button title="New track for audio files" onClick={() => nuova('audio')}><Icon name="plus" size={13} /> Audio</button>
          <button title="New effect return (reverb)" onClick={() => nuova('bus')}><Icon name="plus" size={13} /> Bus</button>
        </div>
        <Playhead player={player} toX={toX} height={contentH} />
      </div>
      {menu && <ContextMenu {...menu} onClose={() => setMenu(null)} />}
    </div>
  )
}

export default memo(Arrange)
export { HEAD_DEFAULT }
