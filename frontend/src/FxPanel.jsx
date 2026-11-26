// Pannello dell'effetto in basso (come il "device view" di un DAW): si apre con un clic
// su un effetto della catena o su un insert del mixer. Manopole per ogni parametro;
// l'EQ ha la curva (linee) e l'analizzatore di spettro (barre); compressore e limiter
// la curva di trasferimento, la riduzione di guadagno nel tempo e un meter che segue
// la riproduzione. Spettro e dinamica arrivano dal server (/api/fxview): lo stesso
// codice del render. Le curve si ridisegnano subito mentre si trascina; il valore
// parte al rilascio (un gesto = un undo).
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icons.jsx'
import { clamp, titleCase } from './util.js'

// ---------------------------------------------------------------- matematica

// coefficienti RBJ: identici a synth.biquad del backend
function biquad(kind, f, q, sr, g = 0) {
  f = clamp(f, 10, sr * 0.45)
  q = Math.max(0.1, q)
  const w = 2 * Math.PI * f / sr, cw = Math.cos(w), sw = Math.sin(w), al = sw / (2 * q), A = 10 ** (g / 40)
  const sa = 2 * Math.sqrt(A) * al
  switch (kind) {
    case 'lowpass': return [(1 - cw) / 2, 1 - cw, (1 - cw) / 2, 1 + al, -2 * cw, 1 - al]
    case 'highpass': return [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2, 1 + al, -2 * cw, 1 - al]
    case 'bandpass': return [al, 0, -al, 1 + al, -2 * cw, 1 - al]
    case 'peak': return [1 + al * A, -2 * cw, 1 - al * A, 1 + al / A, -2 * cw, 1 - al / A]
    case 'lowshelf': return [A * ((A + 1) - (A - 1) * cw + sa), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sa),
      (A + 1) + (A - 1) * cw + sa, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sa]
    case 'highshelf': return [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sa),
      (A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    default: return [1, 0, 0, 1, 0, 0]
  }
}

function magDb(c, f, sr) {
  const w = 2 * Math.PI * f / sr, c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w)
  const nr = c[0] + c[1] * c1 + c[2] * c2, ni = -(c[1] * s1 + c[2] * s2)
  const dr = c[3] + c[4] * c1 + c[5] * c2, di = -(c[4] * s1 + c[5] * s2)
  return 10 * Math.log10(Math.max(1e-30, (nr * nr + ni * ni) / (dr * dr + di * di)))
}

const GEQ = [31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
const geqKey = f => (f >= 1000 ? `g${f / 1000}k` : `g${f}`)

// gli stadi di un effetto di tono, come li applica effects.py: [kind, f, q, gain, volte, banda]
function stages(type, p, sr) {
  const s = []
  if (type === 'eq') {
    if (p.low_cut > 0) s.push(['highpass', p.low_cut, 0.707, 0, 2, 'lc'])
    if (p.low_gain) s.push(['lowshelf', p.low_freq, 0.707, p.low_gain, 1, 'ls'])
    if (p.mid_gain) s.push(['peak', p.mid_freq, p.mid_q, p.mid_gain, 1, 'b1'])
    if (p.mid2_gain) s.push(['peak', p.mid2_freq, p.mid2_q, p.mid2_gain, 1, 'b2'])
    if (p.high_gain) s.push(['highshelf', p.high_freq, 0.707, p.high_gain, 1, 'hs'])
    if (p.high_cut > 0) s.push(['lowpass', p.high_cut, 0.707, 0, 1, 'hc'])
  } else if (type === 'graphic_eq') {
    for (const f of GEQ) if (p[geqKey(f)] && f < sr * 0.45) s.push(['peak', f, 1.4, p[geqKey(f)], 1, geqKey(f)])
  } else if (['lowpass', 'highpass', 'bandpass'].includes(type)) {
    s.push([type, p.cutoff, p.q, 0, p.steep ? 2 : 1, 'f'])
  }
  return s.map(([k, f, q, g, n, band]) => ({ c: biquad(k, f, q, sr, g), n, band }))
}

function response(type, p, sr, f, only) {
  let db = type === 'graphic_eq' ? (p.output_db || 0) : 0
  for (const st of stages(type, p, sr)) if (!only || st.band === only) db += st.n * magDb(st.c, f, sr)
  return db
}

// curva del compressore: identica a effects._gain_computer
function compOut(x, thr, ratio, knee, makeup) {
  const over = x - thr
  let gr = 0
  if (knee > 0 && Math.abs(over) <= knee / 2) gr = (1 / ratio - 1) * (over + knee / 2) ** 2 / (2 * knee)
  else if (over > (knee > 0 ? knee / 2 : 0)) gr = (1 / ratio - 1) * over
  return x + gr + makeup
}

// ---------------------------------------------------------------- manopola

// scala logaritmica per frequenze e tempi; "0 = off" resta in fondo alla corsa
function scale(p) {
  const lo = p.min ?? 0, hi = p.max ?? 1
  const offZero = lo === 0 && p.unit === 'Hz'
  const logLo = offZero ? 20 : lo
  const log = logLo > 0 && hi / logLo >= 20
  return {
    toN: v => {
      if (offZero && v <= 0) return 0
      if (log) return clamp(Math.log(Math.max(v, logLo) / logLo) / Math.log(hi / logLo), 0, 1) * (offZero ? 0.97 : 1) + (offZero ? 0.03 : 0)
      return (v - lo) / (hi - lo || 1)
    },
    fromN: n => {
      n = clamp(n, 0, 1)
      if (offZero && n < 0.03) return 0
      if (log) return logLo * (hi / logLo) ** (offZero ? (n - 0.03) / 0.97 : n)
      return lo + n * (hi - lo)
    },
  }
}

function tidy(v, p) {
  const r = (p.max ?? 1) - (p.min ?? 0)
  if (Math.abs(v) >= 1000) return Math.round(v / 10) * 10
  if (Math.abs(v) >= 100) return Math.round(v)
  if (r > 30 || Math.abs(v) >= 10) return Math.round(v * 10) / 10
  return Math.round(v * 100) / 100
}

export function fmtVal(v, p) {
  if (!p?.unit && p?.min === 0 && p?.max === 1 && /dry\/wet/.test(p.desc || '')) return `${Math.round(v * 100)}%`
  if (p?.unit === 'Hz' && p.min === 0 && v <= 0) return 'off'
  if (p?.unit === 'Hz' && v >= 1000) return `${+(v / 1000).toFixed(v >= 10000 ? 1 : 2)} k`
  const u = p?.unit === 'Hz' ? ' Hz' : p?.unit ? ' ' + p.unit : ''
  return `${tidy(v, p || {})}${u}`
}

export function Knob({ label, value, p, onChange, onCommit, color, size = 46 }) {
  const sc = useMemo(() => scale(p), [p])
  const drag = useRef(null)
  const [edit, setEdit] = useState(false)
  const n = sc.toN(value)
  const a0 = -135, a = a0 + 270 * n
  const r = size / 2 - 5, cx = size / 2, cy = size / 2
  const pt = deg => [cx + r * Math.sin(deg * Math.PI / 180), cy - r * Math.cos(deg * Math.PI / 180)]
  const arc = (d0, d1) => {
    const [x0, y0] = pt(d0), [x1, y1] = pt(d1)
    return `M${x0},${y0} A${r},${r} 0 ${d1 - d0 > 180 ? 1 : 0} 1 ${x1},${y1}`
  }
  const bipolar = (p.min ?? 0) < 0 && (p.max ?? 1) > 0
  const zero = a0 + 270 * sc.toN(0)
  const down = e => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { y: e.clientY, n, v: value }
  }
  const move = e => {
    if (!drag.current) return
    const k = e.shiftKey ? 1000 : 180
    const v = tidy(sc.fromN(drag.current.n + (drag.current.y - e.clientY) / k), p)
    drag.current.v = v
    onChange(v)
  }
  const up = () => {
    const d = drag.current
    drag.current = null
    if (d && d.v !== value) onCommit(d.v)
    else if (d) onCommit(value)
  }
  const wheel = e => {
    e.preventDefault()
    const v = tidy(sc.fromN(n + (e.deltaY < 0 ? 1 : -1) * (e.shiftKey ? 0.005 : 0.025)), p)
    onChange(v)
    onCommit(v)
  }
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.addEventListener('wheel', wheel, { passive: false })
    return () => el.removeEventListener('wheel', wheel)
  })
  return (
    <div className="knob" title={`${p.desc || label} · drag up/down (Shift = fine) · double-click: default`} style={{ '--kc': color }}>
      <svg ref={ref} width={size} height={size} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        onDoubleClick={() => { onChange(p.default); onCommit(p.default) }}>
        <path d={arc(a0, 135)} className="k-track" />
        {n > 0.001 && <path d={bipolar ? arc(Math.min(zero, a), Math.max(zero, a)) : arc(a0, a)} className="k-val" />}
        <circle cx={cx} cy={cy} r={r - 6} className="k-cap" />
        <line x1={cx} y1={cy} x2={pt(a)[0] * 0.62 + cx * 0.38} y2={pt(a)[1] * 0.62 + cy * 0.38} className="k-ptr" />
      </svg>
      {edit
        ? <input className="k-edit" autoFocus defaultValue={value} onBlur={e => { setEdit(false); const v = Number(e.target.value); if (!Number.isNaN(v)) onCommit(clamp(v, p.min ?? -Infinity, p.max ?? Infinity)) }}
          onKeyDown={e => { e.stopPropagation(); if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setEdit(false) }} />
        : <div className="k-value" onDoubleClick={() => setEdit(true)} title="double-click to type">{fmtVal(value, p)}</div>}
      <div className="k-label">{label}</div>
    </div>
  )
}

// ---------------------------------------------------------------- utilita'

export function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(600)
  const [h, setH] = useState(200)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => { setW(el.clientWidth); setH(el.clientHeight) })
    ro.observe(el)
    setW(el.clientWidth); setH(el.clientHeight)
    return () => ro.disconnect()
  }, [])
  return [ref, w, h]
}

const FREQ_GRID = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
const fLabel = f => (f >= 1000 ? `${f / 1000}k` : String(f))
const BAND_COLORS = { lc: '#9b8cff', ls: '#ffb347', b1: '#4fd18b', b2: '#4fc3f7', hs: '#ff6b9a', hc: '#c58cff', f: '#5b8cff' }

// ---------------------------------------------------------------- EQ

function EqGraph({ type, params, spec, sr, view, setLive, commit }) {
  const [ref, W, H] = useWidth()
  const range = type === 'graphic_eq' ? 15 : 20
  const fx = f => (W * Math.log(f / 20)) / Math.log(1000)
  const xf = x => 20 * 1000 ** (clamp(x, 0, W) / W)
  const y = db => H / 2 - (db * (H / 2 - 8)) / range
  const ydb = yy => ((H / 2 - yy) * range) / (H / 2 - 8)
  const drag = useRef(null)

  // curva: ~1 punto ogni 3 px
  const pts = useMemo(() => {
    const n = Math.max(60, Math.round(W / 3))
    return Array.from({ length: n + 1 }, (_, i) => 20 * 1000 ** (i / n))
  }, [W])
  const path = only => pts.map((f, i) => `${i ? 'L' : 'M'}${fx(f).toFixed(1)},${y(clamp(response(type, params, sr, f, only), -range * 1.4, range * 1.4)).toFixed(1)}`).join('')
  const total = path()

  // nodi trascinabili: [banda, chiave freq, chiave gain|null, chiave q|null]
  const nodes = type === 'eq'
    ? [['lc', 'low_cut', null, null, 'Low cut'], ['ls', 'low_freq', 'low_gain', null, 'Low shelf'], ['b1', 'mid_freq', 'mid_gain', 'mid_q', 'Bell 1'],
      ['b2', 'mid2_freq', 'mid2_gain', 'mid2_q', 'Bell 2'], ['hs', 'high_freq', 'high_gain', null, 'High shelf'], ['hc', 'high_cut', null, null, 'High cut']]
    : type === 'graphic_eq' ? [] : [['f', 'cutoff', null, 'q', 'Cutoff']]

  // spettro: l'entrata dal server, l'uscita = entrata + curva (l'EQ e' lineare: e' esatto, e segue il mouse)
  const sp = view?.spectrum
  let bars = null
  if (sp && sp.in.some(v => v > -110)) {
    const top = Math.max(...sp.in, ...sp.in.map((v, i) => v + response(type, params, sr, sp.freqs[i]))) + 3
    const yb = v => clamp(((top - v) / 72) * H, 0, H)
    const k = 2 ** (0.5 / 6)
    bars = sp.freqs.map((f, i) => {
      const x0 = fx(f / k) + 0.5, x1 = fx(f * k) - 0.5
      const vin = sp.in[i], vout = vin + response(type, params, sr, f)
      return <g key={f}>
        <rect className="sp-in" x={x0} width={Math.max(1, x1 - x0)} y={yb(vin)} height={H - yb(vin)} />
        <rect className="sp-out" x={x0 + 1} width={Math.max(1, x1 - x0 - 2)} y={yb(vout)} height={H - yb(vout)} />
      </g>
    })
  }

  const nodePos = ([band, fk, gk]) => {
    const p = spec[fk]
    let f = params[fk]
    const off = p.min === 0 && f <= 0
    if (off) f = fk === 'high_cut' ? 20000 : 20
    const g = gk ? params[gk] : (band === 'f' ? response(type, params, sr, f) : 0)
    return { x: fx(clamp(f, 20, 20000)), y: y(clamp(g, -range, range)), off }
  }

  const down = (e, node) => {
    e.preventDefault(); e.stopPropagation()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { node, changed: {} }
  }
  const move = e => {
    const d = drag.current
    if (!d) return
    const r = e.currentTarget.getBoundingClientRect()
    const [, fk, gk] = d.node
    const pf = spec[fk]
    let f = xf(e.clientX - r.left)
    if (pf.min === 0 && ((fk === 'low_cut' && f < 21) || (fk === 'high_cut' && f > 19500))) f = 0
    else f = clamp(f, Math.max(pf.min, 20), pf.max)
    f = f >= 1000 ? Math.round(f / 10) * 10 : Math.round(f)
    const ch = { [fk]: f }
    if (gk) ch[gk] = clamp(Math.round(ydb(e.clientY - r.top) * 10) / 10, spec[gk].min, spec[gk].max)
    Object.assign(d.changed, ch)
    setLive(ch)
  }
  const up = () => {
    const d = drag.current
    drag.current = null
    if (d && Object.keys(d.changed).length) commit(d.changed)
  }
  // rotella su un nodo: larghezza (Q)
  const qTimer = useRef(null)
  const wheelNode = (e, node) => {
    const qk = node[3]
    if (!qk) return
    e.preventDefault()
    const q = clamp(Math.round(params[qk] * (e.deltaY < 0 ? 1.12 : 1 / 1.12) * 100) / 100, spec[qk].min, spec[qk].max)
    setLive({ [qk]: q })
    clearTimeout(qTimer.current)
    qTimer.current = setTimeout(() => commit({ [qk]: q }), 350)
  }
  const resetNode = ([, fk, gk]) => commit(gk ? { [gk]: 0 } : { [fk]: spec[fk].min === 0 ? 0 : spec[fk].default })

  // EQ grafico: barre verticali da trascinare
  const geqDown = (e, f) => {
    e.preventDefault()
    e.currentTarget.closest('svg').setPointerCapture(e.pointerId)
    drag.current = { geq: geqKey(f), changed: {} }
  }
  const geqMove = e => {
    const d = drag.current
    if (!d?.geq) return move(e)
    const r = e.currentTarget.getBoundingClientRect()
    const g = clamp(Math.round(ydb(e.clientY - r.top) * 2) / 2, -12, 12)
    d.changed = { [d.geq]: g }
    setLive(d.changed)
  }

  return (
    <div className="eq-graph" ref={ref}>
      <svg width={W} height={H} onPointerMove={geqMove} onPointerUp={up} onPointerCancel={up}>
        {bars}
        {FREQ_GRID.map(f => <g key={f}><line className="g-line" x1={fx(f)} x2={fx(f)} y1={0} y2={H} />
          <text className="g-text" x={fx(f) + 3} y={H - 4}>{fLabel(f)}</text></g>)}
        {[-18, -12, -6, 0, 6, 12, 18].filter(d => Math.abs(d) <= range).map(d => <g key={d}>
          <line className={'g-line' + (d === 0 ? ' zero' : '')} x1={0} x2={W} y1={y(d)} y2={y(d)} />
          <text className="g-text" x={W - 4} y={y(d) - 2} textAnchor="end">{d > 0 ? '+' + d : d}</text></g>)}
        {type === 'eq' && nodes.map(nd => (params[nd[2]] || (nd[2] === null && params[nd[1]] > 0)) &&
          <path key={nd[0]} d={path(nd[0])} className="band-curve" style={{ stroke: BAND_COLORS[nd[0]] }} />)}
        <path d={`${total}L${W},${y(0)}L0,${y(0)}Z`} className="eq-fill" />
        <path d={total} className="eq-curve" />
        {type === 'graphic_eq' && GEQ.map(f => {
          const g = params[geqKey(f)] || 0, x = fx(f)
          return <g key={f} className="geq-bar" onPointerDown={e => geqDown(e, f)} onDoubleClick={() => commit({ [geqKey(f)]: 0 })}>
            <rect x={x - 9} width={18} y={0} height={H} className="geq-hit" />
            <rect x={x - 5} width={10} y={Math.min(y(g), y(0))} height={Math.abs(y(g) - y(0)) || 1} className="geq-fill" />
            <rect x={x - 9} width={18} y={y(g) - 3} height={6} rx={2} className="geq-cap" />
            <text className="g-text c" x={x} y={14} textAnchor="middle">{g > 0 ? '+' : ''}{g}</text>
          </g>
        })}
        {nodes.map(nd => {
          const { x, y: yy, off } = nodePos(nd)
          return <g key={nd[0]} className={'eq-node' + (off ? ' off' : '')} style={{ '--nc': BAND_COLORS[nd[0]] }}
            onPointerDown={e => down(e, nd)}
            onWheel={e => wheelNode(e, nd)} onDoubleClick={() => resetNode(nd)}>
            <title>{nd[4]} · drag{nd[2] ? ' (left/right = frequency, up/down = gain)' : ''}{nd[3] ? ' · wheel = width (Q)' : ''} · double-click: reset</title>
            <circle cx={x} cy={yy} r={9} />
            <text x={x} y={yy + 3.5} textAnchor="middle">{nd[0] === 'f' ? '●' : nodes.indexOf(nd) + 1}</text>
          </g>
        })}
      </svg>
    </div>
  )
}

const EQ_BANDS = [['lc', 'Low cut', ['low_cut']], ['ls', 'Low shelf', ['low_freq', 'low_gain']], ['b1', 'Bell 1', ['mid_freq', 'mid_gain', 'mid_q']],
  ['b2', 'Bell 2', ['mid2_freq', 'mid2_gain', 'mid2_q']], ['hs', 'High shelf', ['high_freq', 'high_gain']], ['hc', 'High cut', ['high_cut']]]
// etichette brevi sotto le manopole delle bande dell'EQ
const EQ_SHORT = { low_cut: 'Freq', high_cut: 'Freq', low_freq: 'Freq', mid_freq: 'Freq', mid2_freq: 'Freq', high_freq: 'Freq',
  low_gain: 'Gain', mid_gain: 'Gain', mid2_gain: 'Gain', high_gain: 'Gain', mid_q: 'Q', mid2_q: 'Q' }
const SHORT = { threshold_db: 'Threshold', ratio: 'Ratio', attack_ms: 'Attack', release_ms: 'Release', knee_db: 'Knee', makeup_db: 'Makeup',
  mix: 'Mix', gain_db: 'Gain', ceiling_db: 'Ceiling', output_db: 'Output' }

function EqEditor(props) {
  const { type, params, spec, knob } = props
  return (
    <div className="fx-body eq">
      <EqGraph {...props} />
      {type === 'eq' && <div className="eq-bands">
        {EQ_BANDS.map(([b, name, keys]) => <div key={b} className="band-col" style={{ '--bc': BAND_COLORS[b] }}>
          <div className="band-name">{name}</div>
          <div className="knobs">{keys.map(k => knob(k, EQ_SHORT[k], BAND_COLORS[b]))}</div>
        </div>)}
      </div>}
      {type === 'graphic_eq' && <div className="knobs">{knob('output_db', 'Output')}</div>}
      {['lowpass', 'highpass', 'bandpass'].includes(type) && <div className="knobs">
        {knob('cutoff', 'Cutoff')}{knob('q', 'Resonance')}
        <Toggle on={!!params.steep} label={spec.steep?.desc || 'steep'} onClick={() => props.commit({ steep: !params.steep })} />
      </div>}
    </div>
  )
}

// ---------------------------------------------------------------- dinamica

// livello nel tempo (grigio), uscita (linea), riduzione di guadagno (rossa, dall'alto)
function DynTimeline({ view, player, busy }) {
  const [ref, W, H] = useWidth()
  const t = view?.time
  const ph = useRef(null)
  useEffect(() => player?.onFrame(s => {
    const el = ph.current
    if (!el || !view) return
    el.setAttribute('transform', `translate(${(s / view.duration_s) * W},0)`)
  }), [player, view, W])
  if (!t) return <div className="dyn-time" ref={ref}><p className="hint pad">{busy || !view ? 'Measuring…' : 'No audio reaches this effect yet.'}</p></div>
  const n = t.in_db.length
  const x = i => (i / Math.max(1, n - 1)) * W
  const yl = db => clamp((-db / 60) * H, 0, H)       // 0 dB in alto, -60 in basso
  const yg = db => clamp((-db / 24) * (H * 0.5), 0, H * 0.5)
  const area = t.in_db.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${yl(v).toFixed(1)}`).join('') + `L${W},${H}L0,${H}Z`
  const out = t.out_db.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${yl(v).toFixed(1)}`).join('')
  const gr = t.gr_db.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${yg(v).toFixed(1)}`).join('') + `L${W},0L0,0Z`
  return (
    <div className="dyn-time" ref={ref}>
      <svg width={W} height={H}>
        {[-6, -12, -24, -48].map(d => <g key={d}><line className="g-line" x1={0} x2={W} y1={yl(d)} y2={yl(d)} />
          <text className="g-text" x={4} y={yl(d) - 2}>{d} dB</text></g>)}
        <path d={area} className="dyn-in" />
        <path d={out} className="dyn-out" />
        <path d={gr} className="dyn-gr" />
        <text className="g-text gr" x={W - 4} y={12} textAnchor="end">gain reduction</text>
        <line ref={ph} x1={0} x2={0} y1={0} y2={H} className="dyn-ph" />
      </svg>
    </div>
  )
}

// meter verticale della riduzione di guadagno che segue la riproduzione
function GrMeter({ view, player }) {
  const bar = useRef(null), txt = useRef(null), inb = useRef(null), outb = useRef(null)
  useEffect(() => player?.onFrame(s => {
    const t = view?.time
    if (!t || !bar.current) return
    const i = clamp(Math.floor(s / t.step_s), 0, t.gr_db.length - 1)
    const g = t.gr_db[i]
    bar.current.style.height = `${clamp(-g / 24, 0, 1) * 100}%`
    txt.current.textContent = g < -0.05 ? g.toFixed(1) : '0.0'
    inb.current.style.height = `${clamp(1 + t.in_db[i] / 60, 0, 1) * 100}%`
    outb.current.style.height = `${clamp(1 + t.out_db[i] / 60, 0, 1) * 100}%`
  }), [player, view])
  return (
    <div className="gr-meter">
      <div className="meters">
        <div className="mtr" title="Input level"><i ref={inb} /><small>IN</small></div>
        <div className="mtr gr" title="Gain reduction (0 to -24 dB)"><i ref={bar} /><small>GR</small></div>
        <div className="mtr" title="Output level"><i ref={outb} /><small>OUT</small></div>
      </div>
      <b ref={txt}>0.0</b><small>dB GR</small>
    </div>
  )
}

function TransferCurve({ params, view, setLive, commit }) {
  const S = 190
  const pos = db => ((db + 60) / 60) * S
  const thr = params.threshold_db, ratio = Math.max(1, params.ratio), knee = params.knee_db, mk = params.makeup_db || 0
  const pts = Array.from({ length: 121 }, (_, i) => -60 + i * 0.5)
  const d = pts.map((x, i) => `${i ? 'L' : 'M'}${pos(x)},${S - pos(clamp(compOut(x, thr, ratio, knee, mk), -60, 6))}`).join('')
  const drag = useRef(null)
  const move = e => {
    if (!drag.current) return
    const r = e.currentTarget.getBoundingClientRect()
    const t = clamp(Math.round(((e.clientX - r.left) / S) * 60 - 60), -60, 0)
    drag.current.v = t
    setLive({ threshold_db: t })
  }
  const up = () => { const v = drag.current?.v; drag.current = null; if (v !== undefined) commit({ threshold_db: v }) }
  const h = view?.detector_hist
  return (
    <svg className="transfer" width={S} height={S} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
      onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = {}; move(e) }}>
      <title>Input → output. Drag left/right to move the threshold. Bars: how often the signal sits at each level.</title>
      {h && h.map((v, i) => v > 0 && <rect key={i} className="hist" x={(i / 60) * S} width={S / 60} y={S - v * S * 0.35} height={v * S * 0.35} />)}
      {[-48, -36, -24, -12].map(v => <g key={v}><line className="g-line" x1={pos(v)} x2={pos(v)} y1={0} y2={S} />
        <line className="g-line" x1={0} x2={S} y1={S - pos(v)} y2={S - pos(v)} /></g>)}
      <line className="g-line zero" x1={0} y1={S} x2={S} y2={0} strokeDasharray="3 3" />
      <line className="thr" x1={pos(thr)} x2={pos(thr)} y1={0} y2={S} />
      {knee > 0 && <rect className="knee" x={pos(thr - knee / 2)} width={pos(thr + knee / 2) - pos(thr - knee / 2)} y={0} height={S} />}
      <path d={d} className="eq-curve" />
      <circle className="thr-dot" cx={pos(thr)} cy={S - pos(clamp(compOut(thr, thr, ratio, knee, mk), -60, 6))} r={5} />
      <text className="g-text" x={4} y={12}>out</text><text className="g-text" x={S - 4} y={S - 4} textAnchor="end">in</text>
      <text className="g-text c" x={clamp(pos(thr) + 4, 4, S - 50)} y={S - 16}>{thr} dB</text>
    </svg>
  )
}

function DynEditor({ type, params, spec, view, player, knob, setLive, commit, busy }) {
  const keys = Object.keys(spec)
  const comp = type === 'compressor'
  const match = view && view.in.lufs > -69 && view.out.lufs > -69
    ? Math.round(((params.makeup_db || 0) + view.in.lufs - view.out.lufs) * 10) / 10 : null
  const ord = comp ? ['threshold_db', 'ratio', 'knee_db', 'attack_ms', 'release_ms', 'makeup_db', 'mix'] : keys
  return (
    <div className="fx-body dyn">
      <div className="dyn-top">
        {comp && <TransferCurve params={params} view={view} setLive={setLive} commit={commit} />}
        <DynTimeline view={view} player={player} busy={busy} />
        <GrMeter view={view} player={player} />
      </div>
      <div className="dyn-bottom">
        <div className="knobs">{ord.filter(k => spec[k] && spec[k].type !== 'bool' && spec[k].type !== 'choice').map(k => knob(k, SHORT[k]))}</div>
        {comp && <div className="ratio-presets">
          <span className="hint">Ratio</span>
          {[1.5, 2, 4, 8, 20].map(r => <button key={r} className={Math.abs(params.ratio - r) < 0.01 ? 'on' : ''} onClick={() => commit({ ratio: r })}>{r === 20 ? '∞' : r}:1</button>)}
          <button title="Set the make-up gain so the output is as loud as the input (LUFS)" disabled={match === null || !spec.makeup_db}
            onClick={() => commit({ makeup_db: clamp(match, spec.makeup_db.min, spec.makeup_db.max) })}>Match level</button>
        </div>}
        <Stats view={view} />
      </div>
    </div>
  )
}

function Stats({ view }) {
  if (!view) return null
  return (
    <div className="fx-stats">
      <div><span>In</span><b>{view.in.lufs} LUFS</b><small>peak {view.in.peak_db} dB</small></div>
      <div><span>Out</span><b>{view.out.lufs} LUFS</b><small>peak {view.out.peak_db} dB</small></div>
      {view.gr && <div><span>GR</span><b className={view.gr.max_db < -12 ? 'bad' : ''}>{view.gr.max_db} dB max</b><small>{view.gr.avg_db} dB average</small></div>}
    </div>
  )
}

// ---------------------------------------------------------------- generico

function Toggle({ on, label, onClick }) {
  return <button className={'fx-toggle' + (on ? ' on' : '')} onClick={onClick} title={label}><i />{label}</button>
}

function Generic({ spec, params, knob, commit, view }) {
  const entries = Object.entries(spec)
  return (
    <div className="fx-body generic">
      <div className="knobs">{entries.filter(([, p]) => p.type !== 'bool' && p.type !== 'choice').map(([k]) => knob(k, SHORT[k]))}</div>
      <div className="fx-opts">
        {entries.filter(([, p]) => p.type === 'choice').map(([k, p]) => <div key={k} className="seg" title={p.desc}>
          <span className="hint">{titleCase(k)}</span>
          {p.choices.length <= 7
            ? p.choices.map(c => <button key={c} className={params[k] === c ? 'on' : ''} onClick={() => commit({ [k]: c })}>{c}</button>)
            : <select value={params[k]} onChange={e => commit({ [k]: e.target.value })}>{p.choices.map(c => <option key={c}>{c}</option>)}</select>}
        </div>)}
        {entries.filter(([, p]) => p.type === 'bool').map(([k, p]) => <Toggle key={k} on={!!params[k]} label={p.desc || k} onClick={() => commit({ [k]: !params[k] })} />)}
      </div>
      <Stats view={view} />
    </div>
  )
}

// ---------------------------------------------------------------- pannello

// "predelay_ms" -> "Predelay": l'unita' e' gia' scritta sotto il valore
const nomeParam = k => titleCase(k.replace(/_(ms|db|hz)$/, ''))

const TONO = ['eq', 'graphic_eq', 'lowpass', 'highpass', 'bandpass']
const DIN = ['compressor', 'limiter', 'gate', 'deesser', 'multiband', 'transient', 'pump']

export default function FxPanel({ project, target, index, catalog, run, player, revision, height, onSelect, onClose, embedded = false }) {
  const track = target === 'master' ? null : project.tracks.find(t => t.id === target)
  const effects = target === 'master' ? project.master.effects : track?.effects || []
  const e = effects[index]
  const spec = useMemo(() => (catalog || []).find(x => x.name === e?.type)?.params || {}, [catalog, e?.type])
  const saved = useMemo(() => ({ ...Object.fromEntries(Object.entries(spec).map(([k, p]) => [k, p.default])), ...(e?.params || {}) }), [spec, e])
  const [live, setLiveState] = useState({})
  useEffect(() => { setLiveState({}) }, [saved])
  const params = { ...saved, ...live }
  const setLive = useCallback(ch => setLiveState(l => ({ ...l, ...ch })), [])
  const commit = useCallback(ch => {
    const diff = Object.fromEntries(Object.entries(ch).filter(([k, v]) => v !== saved[k]))
    if (!Object.keys(diff).length) { setLiveState({}); return }
    setLive(diff)
    run('update_effect', { target, index, params: diff })
  }, [saved, run, target, index, setLive])

  // misura dal server, dopo ogni modifica (un attimo dopo: non a ogni passo)
  const [view, setView] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const need = !!e
  useEffect(() => {
    if (!need) return
    let vivo = true
    const t = setTimeout(async () => {
      setBusy(true)
      try {
        const v = await api(`/api/fxview?target=${encodeURIComponent(target)}&index=${index}`)
        if (vivo) { setView(v); setErr('') }
      } catch (x) { if (vivo) setErr(x.message) }
      if (vivo) setBusy(false)
    }, 250)
    return () => { vivo = false; clearTimeout(t) }
  }, [target, index, revision, e?.type, need])
  useEffect(() => { setView(null) }, [target, index, e?.type])

  if (!e) return null
  const knob = (k, label, color) => spec[k] && <Knob key={k} label={label || nomeParam(k)} value={params[k]} p={spec[k]} color={color}
    onChange={v => setLive({ [k]: v })} onCommit={v => commit({ [k]: v })} />
  const props = { type: e.type, params, spec, sr: project.sample_rate, view, player, knob, setLive, commit, busy }
  const nome = track ? track.name : 'Master'
  const body = TONO.includes(e.type) ? <EqEditor {...props} />
    : DIN.includes(e.type) ? <DynEditor {...props} />
      : <Generic {...props} />
  // dentro il pannello traccia: solo l'editor, con nome, descrizione e Reset
  if (embedded) return (
    <div className={'fx-embedded' + (e.enabled === false ? ' bypass' : '')}>
      <div className="fx-subbar">
        <b>{titleCase(e.type)}</b>
        <span className="hint ellipsis grow">{(catalog || []).find(x => x.name === e.type)?.desc}</span>
        {busy && <span className="hint">measuring…</span>}
        {err && <span className="warn" title={err}>!</span>}
        <button title="Back to the default settings" onClick={() => commit(Object.fromEntries(Object.entries(spec).map(([k, p]) => [k, p.default])))}>Reset</button>
      </div>
      {body}
    </div>
  )
  return (
    <div className={'fxpanel' + (e.enabled === false ? ' bypass' : '')} style={{ height }}>
      <div className="fx-bar">
        <button className={'fx-power' + (e.enabled !== false ? ' on' : '')} title={e.enabled === false ? 'Bypassed: click to turn on' : 'On: click to bypass'}
          onClick={() => run('update_effect', { target, index, enabled: e.enabled === false })}><Icon name="power" size={13} /></button>
        <span className="fx-where" style={{ '--c': track?.color || 'var(--accent)' }}>{nome}</span>
        <div className="fx-chain">
          {effects.map((x, i) => <button key={i} className={(i === index ? 'on' : '') + (x.enabled === false ? ' off' : '')}
            onClick={() => onSelect(i)}>{titleCase(x.type)}</button>)}
        </div>
        <span className="hint ellipsis grow">{(catalog || []).find(x => x.name === e.type)?.desc}</span>
        {busy && <span className="hint">measuring…</span>}
        {err && <span className="warn" title={err}>!</span>}
        <button title="Back to the default settings" onClick={() => commit(Object.fromEntries(Object.entries(spec).map(([k, p]) => [k, p.default])))}>Reset</button>
        <button className="icon-btn" title="Move left" disabled={index === 0} onClick={() => { run('move_effect', { target, index, to: index - 1 }); onSelect(index - 1) }}><Icon name="up" size={12} /></button>
        <button className="icon-btn" title="Move right" disabled={index === effects.length - 1} onClick={() => { run('move_effect', { target, index, to: index + 1 }); onSelect(index + 1) }}><Icon name="down" size={12} /></button>
        <button className="icon-btn" title="Remove the effect" onClick={() => { run('remove_effect', { target, index }); onClose() }}><Icon name="trash" size={13} /></button>
        <button className="icon-btn" title="Close (Esc)" onClick={onClose}>✕</button>
      </div>
      {body}
    </div>
  )
}
