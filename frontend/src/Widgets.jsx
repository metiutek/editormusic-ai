// Piccoli pezzi riusati: rinomina sul posto, menu col tasto destro, cursore di
// riproduzione che si muove senza ridisegnare React.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import Icon from './Icons.jsx'

// Campo di testo che compare al posto di un nome. Invio o clic fuori = salva,
// Esc = annulla. Non lascia passare tasti e clic a chi sta sotto.
export function InlineEdit({ value, onCommit, onCancel, className = '' }) {
  const [v, setV] = useState(value ?? '')
  const ref = useRef(null)
  const fatto = useRef(false)
  useLayoutEffect(() => { const el = ref.current; if (el) { el.focus(); el.select() } }, [])
  const chiudi = salva => {
    if (fatto.current) return
    fatto.current = true
    const n = v.trim()
    if (salva && n && n !== value) onCommit(n)
    else onCancel?.()
  }
  return (
    <input ref={ref} className={'inline-edit ' + className} value={v} spellCheck={false}
      onChange={e => setV(e.target.value)}
      onBlur={() => chiudi(true)}
      onKeyDown={e => {
        e.stopPropagation()
        if (e.key === 'Enter') chiudi(true)
        else if (e.key === 'Escape') chiudi(false)
      }}
      onPointerDown={e => e.stopPropagation()} onClick={e => e.stopPropagation()} onDoubleClick={e => e.stopPropagation()} />
  )
}

// Menu contestuale: items = [{label, icon, onClick, danger, disabled, hint} | '-']
export function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null)
  const [pos, setPos] = useState({ left: x, top: y })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    setPos({ left: Math.max(4, Math.min(x, window.innerWidth - r.width - 4)), top: Math.max(4, Math.min(y, window.innerHeight - r.height - 4)) })
  }, [x, y])
  useEffect(() => {
    const fuori = e => { if (!ref.current?.contains(e.target)) onClose() }
    const tasto = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('pointerdown', fuori, true)
    window.addEventListener('keydown', tasto, true)
    window.addEventListener('blur', onClose)
    window.addEventListener('wheel', onClose, { passive: true })
    return () => {
      window.removeEventListener('pointerdown', fuori, true)
      window.removeEventListener('keydown', tasto, true)
      window.removeEventListener('blur', onClose)
      window.removeEventListener('wheel', onClose)
    }
  }, [onClose])
  return (
    <div className="ctx-menu" ref={ref} style={pos} onContextMenu={e => e.preventDefault()}>
      {items.filter(Boolean).map((it, i) => it === '-' ? <div key={i} className="ctx-sep" /> : (
        <button key={i} className={it.danger ? 'danger' : ''} disabled={it.disabled}
          onClick={() => { onClose(); it.onClick() }}>
          <span className="ctx-ico">{it.icon && <Icon name={it.icon} size={13} />}</span>
          <span className="grow">{it.label}</span>
          {it.hint && <small>{it.hint}</small>}
        </button>))}
    </div>
  )
}

// Linea del cursore. toX(secondi) -> pixel, o null per nasconderla.
export function Playhead({ player, toX, height, className = 'playhead' }) {
  const ref = useRef(null)
  const f = useRef(toX)
  f.current = toX
  useEffect(() => player.onFrame(t => {
    const el = ref.current
    if (!el) return
    const x = f.current(t)
    if (x === null) { el.style.display = 'none'; return }
    el.style.display = ''
    el.style.transform = `translateX(${x}px)`
  }), [player])
  // ridisegna subito quando cambiano zoom o scorrimento
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const x = toX(player.position())
    el.style.display = x === null ? 'none' : ''
    if (x !== null) el.style.transform = `translateX(${x}px)`
  })
  return <div ref={ref} className={className} style={{ height }} />
}

// Valore che segue il cursore (testo), per l'orologio del trasporto.
export function Live({ player, format }) {
  const ref = useRef(null)
  const f = useRef(format)
  f.current = format
  useEffect(() => player.onFrame(t => { if (ref.current) ref.current.textContent = f.current(t) }), [player])
  useLayoutEffect(() => { if (ref.current) ref.current.textContent = format(player.position()) })
  return <span ref={ref} />
}

// Slider/fader che manda il valore al rilascio, anche se il puntatore
// esce dal controllo (onPointerUp sull'input non basta).
export function useCommitOnRelease(commit) {
  const val = useRef(null)
  const c = useRef(commit)
  c.current = commit
  return {
    set: v => { val.current = v },
    onPointerDown: () => {
      val.current = null
      const up = () => {
        window.removeEventListener('pointerup', up, true)
        window.removeEventListener('pointercancel', up, true)
        // dopo l'ultimo onChange
        setTimeout(() => { if (val.current !== null) c.current(val.current); val.current = null }, 0)
      }
      window.addEventListener('pointerup', up, true)
      window.addEventListener('pointercancel', up, true)
    },
  }
}
