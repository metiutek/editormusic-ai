// Divisori trascinabili: pannello laterale, piano roll, intestazioni delle tracce.
// La misura scelta resta (localStorage) da una sessione all'altra.
import { useCallback, useEffect, useRef, useState } from 'react'
import { clamp } from './util.js'

export function useSize(key, initial, min, max) {
  const [v, setV] = useState(() => {
    try {
      const s = Number(localStorage.getItem('medit.size.' + key))
      return s ? clamp(s, min, max) : initial
    } catch { return initial }
  })
  const set = useCallback(x => {
    const n = clamp(Math.round(x), min, max)
    setV(n)
    try { localStorage.setItem('medit.size.' + key, String(n)) } catch { /* senza storage: solo per ora */ }
  }, [key, min, max])
  return [v, set]
}

// dir: 'x' (barra verticale, si trascina in orizzontale) o 'y'.
// sign: +1 se trascinare verso destra/giu' fa crescere la misura, -1 al contrario.
export default function Splitter({ dir = 'x', value, onChange, sign = 1, title, onReset }) {
  const start = useRef(null)
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!on) return
    const move = e => {
      const d = (dir === 'x' ? e.clientX : e.clientY) - start.current.p
      onChange(start.current.v + d * sign)
    }
    const up = () => setOn(false)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    document.body.style.cursor = dir === 'x' ? 'col-resize' : 'row-resize'
    document.body.style.userSelect = 'none'
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [on])
  return (
    <div className={'splitter ' + dir + (on ? ' on' : '')} title={title || 'Drag to resize · double-click to reset'}
      onPointerDown={e => { e.preventDefault(); start.current = { p: dir === 'x' ? e.clientX : e.clientY, v: value }; setOn(true) }}
      onDoubleClick={onReset} />
  )
}
