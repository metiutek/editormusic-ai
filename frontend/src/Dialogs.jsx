// Finestre: nuova canzone, apri/importa (sfoglia il disco), esporta, domande dell'assistente.
import { useEffect, useState } from 'react'
import { api } from './api.js'

export function Modal({ title, onClose, children }) {
  return (
    <div className="modal-bg" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <div className="modal-head"><b>{title}</b><button className="icon-btn" onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  )
}

const KEYS = ['C', 'C#', 'Db', 'D', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

export function NewSong({ modes, home, onCreate, onClose }) {
  const [f, setF] = useState({ name: 'untitled', bpm: 120, key: 'C', mode: 'major', ts: '4/4', path: '' })
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  const crea = () => {
    const [a, b] = f.ts.split('/').map(Number)
    const path = f.path.trim() || null
    onCreate({ name: f.name, bpm: Number(f.bpm), key: f.key, mode: f.mode, time_sig: [a, b],
      path: path && !path.toLowerCase().endsWith('.json') ? `${path.replace(/[\\/]$/, '')}/${f.name || 'song'}.json` : path })
  }
  return (
    <Modal title="New song" onClose={onClose}>
      <div className="grid2">
        <label className="field"><span>Name</span><input value={f.name} onChange={e => set('name', e.target.value)} /></label>
        <label className="field"><span>Tempo (BPM)</span><input type="number" min={20} max={400} value={f.bpm} onChange={e => set('bpm', e.target.value)} /></label>
        <label className="field"><span>Key</span><select value={f.key} onChange={e => set('key', e.target.value)}>{KEYS.map(k => <option key={k}>{k}</option>)}</select></label>
        <label className="field"><span>Mode</span><select value={f.mode} onChange={e => set('mode', e.target.value)}>{(modes || ['major', 'minor']).map(m => <option key={m}>{m}</option>)}</select></label>
        <label className="field"><span>Time signature</span><select value={f.ts} onChange={e => set('ts', e.target.value)}>{['4/4', '3/4', '6/8', '2/4', '5/4', '7/8', '12/8'].map(t => <option key={t}>{t}</option>)}</select></label>
      </div>
      <label className="field wide"><span>Save in (folder or .json file; empty = decide later)</span>
        <input placeholder={home} value={f.path} onChange={e => set('path', e.target.value)} /></label>
      <div className="modal-foot">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" onClick={crea}>Create</button>
      </div>
    </Modal>
  )
}

export function Browse({ mode, home, onPick, onClose }) {
  const [dir, setDir] = useState(null)
  const [err, setErr] = useState('')
  const [chosen, setChosen] = useState([])
  const go = async p => {
    try { setDir(await api('/api/browse' + (p ? `?path=${encodeURIComponent(p)}` : ''))); setErr('') } catch (e) { setErr(e.message) }
  }
  useEffect(() => { go(home) }, [])
  const click = f => {
    if (f.dir) return go(f.path)
    if (mode === 'open') return onPick([f.path])
    if (f.kind !== 'doc') setChosen(c => c.includes(f.path) ? c.filter(x => x !== f.path) : [...c, f.path])
  }
  const icona = f => f.dir ? '📁' : f.kind === 'doc' ? '📄' : f.kind === 'midi' ? '🎹' : '🎵'
  return (
    <Modal title={mode === 'open' ? 'Open a song, an audio file or a MIDI file' : 'Import audio or MIDI'} onClose={onClose}>
      <div className="row">
        <input className="grow" value={dir?.path || ''} onChange={e => setDir(d => ({ ...d, path: e.target.value }))}
          onKeyDown={e => e.key === 'Enter' && go(e.target.value)} />
        <button onClick={() => go(dir?.parent)}>Up</button>
        {dir?.roots?.map(r => <button key={r} onClick={() => go(r)}>{r}</button>)}
      </div>
      {err && <p className="warn">{err}</p>}
      <div className="files">
        {dir?.entries?.map(f => (
          <div key={f.path} className={'file' + (chosen.includes(f.path) ? ' sel' : '') + (f.dir ? ' dir' : '')}
            onClick={() => click(f)} onDoubleClick={() => !f.dir && onPick([f.path])}>
            <span>{icona(f)}</span> {f.name}
          </div>))}
        {dir && !dir.entries.length && <p className="hint">No songs, audio or MIDI files here.</p>}
      </div>
      {mode === 'import' && <div className="modal-foot">
        <span className="hint">{chosen.length} selected · they go on new tracks at the playhead</span>
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!chosen.length} onClick={() => onPick(chosen)}>Import</button>
      </div>}
    </Modal>
  )
}

export function Export({ project, home, path, onClose, onDone }) {
  const base = (path ? path.replace(/\.json$/i, '') : `${home}/${project?.name || 'song'}`)
  const [kind, setKind] = useState('audio')
  const [fmt, setFmt] = useState('wav')
  const [out, setOut] = useState(`${base}.wav`)
  const [bits, setBits] = useState(24)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (kind === 'audio') setOut(`${base}.${fmt}`)
    else if (kind === 'midi') setOut(`${base}.mid`)
    else setOut(`${base}_stems`)
  }, [kind, fmt])
  const vai = async () => {
    setBusy(true); setErr('')
    try { onDone(await api('/api/export', { body: { path: out, kind, format: fmt, bit_depth: Number(bits) } })) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  return (
    <Modal title="Export" onClose={onClose}>
      <div className="row">
        {[['audio', 'Mixdown'], ['stems', 'Stems (one file per track)'], ['midi', 'MIDI file']].map(([k, n]) =>
          <button key={k} className={kind === k ? 'primary' : ''} onClick={() => setKind(k)}>{n}</button>)}
      </div>
      {kind !== 'midi' && <div className="row">
        <label className="field"><span>Format</span><select value={fmt} onChange={e => setFmt(e.target.value)}>
          {['wav', 'flac', 'mp3', 'ogg', 'aiff'].map(f => <option key={f}>{f}</option>)}</select></label>
        {['wav', 'flac', 'aiff'].includes(fmt) && <label className="field"><span>Bits</span>
          <select value={bits} onChange={e => setBits(e.target.value)}>{[16, 24, 32].map(b => <option key={b}>{b}</option>)}</select></label>}
      </div>}
      <label className="field wide"><span>{kind === 'stems' ? 'Folder' : 'File'}</span><input value={out} onChange={e => setOut(e.target.value)} /></label>
      {err && <p className="warn">{err}</p>}
      <div className="modal-foot">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={busy} onClick={vai}>{busy ? 'Rendering…' : 'Export'}</button>
      </div>
    </Modal>
  )
}

// Domande dell'assistente (ask_user) e conferma degli export: si risponde qui.
export function Questions({ q, onAnswer }) {
  const [scelte, setScelte] = useState({})
  const [altro, setAltro] = useState({})
  const lista = q.domande || []
  const pronta = lista.every((_, i) => (scelte[i]?.length > 0) || (altro[i] || '').trim())
  const tocca = (i, etichetta, multipla) => setScelte(s => {
    const ora = s[i] || []
    if (!multipla) return { ...s, [i]: ora[0] === etichetta ? [] : [etichetta] }
    return { ...s, [i]: ora.includes(etichetta) ? ora.filter(x => x !== etichetta) : [...ora, etichetta] }
  })
  const invia = () => {
    const risposte = {}
    lista.forEach((d, i) => {
      const scritto = (altro[i] || '').trim()
      const sc = scelte[i] || []
      risposte[d.domanda] = d.multipla ? [...sc, ...(scritto ? [scritto] : [])] : (scritto || sc[0])
    })
    onAnswer(risposte)
  }
  return (
    <Modal title="The assistant asks you" onClose={() => onAnswer({ __annulla__: true })}>
      {lista.map((d, i) => (
        <div key={i} className="domanda">
          {d.titolo && <span className="tag">{d.titolo}</span>}
          <p><b>{d.domanda}</b></p>
          {d.opzioni.map(o => {
            const on = (scelte[i] || []).includes(o.etichetta)
            return (
              <button key={o.etichetta} className={'opzione' + (on ? ' on' : '')} onClick={() => tocca(i, o.etichetta, d.multipla)}>
                <span className={'spunta' + (d.multipla ? ' quadra' : '')} />
                <span className="otesto"><b>{o.etichetta}</b>{o.descrizione && <small>{o.descrizione}</small>}</span>
              </button>)
          })}
          <input className="altro" placeholder="Other: write your answer" value={altro[i] || ''}
            onChange={e => setAltro(a => ({ ...a, [i]: e.target.value }))}
            onKeyDown={e => { if (e.key === 'Enter' && pronta) invia() }} />
          {d.multipla && <p className="hint">You can pick more than one.</p>}
        </div>))}
      <div className="modal-foot">
        <button onClick={() => onAnswer({ __annulla__: true })}>Don't answer</button>
        <button className="primary" disabled={!pronta} onClick={invia}>Answer</button>
      </div>
    </Modal>
  )
}
