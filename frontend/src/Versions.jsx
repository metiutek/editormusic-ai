// Versioni nominate del documento (Store.snapshot): undo torna indietro, una
// versione si tiene e si confronta. Le stesse operazioni dell'agente MCP.
import { useEffect, useState } from 'react'
import { op } from './api.js'
import Icon from './Icons.jsx'

export default function Versions({ revision, run }) {
  const [list, setList] = useState([])
  const [name, setName] = useState('')
  const [diff, setDiff] = useState(null)
  const carica = () => op('snapshots').then(r => setList(r.result || [])).catch(() => setList([]))
  useEffect(() => { carica() }, [revision])

  const salva = async () => {
    const n = name.trim() || `version ${list.length + 1}`
    if (await run('snapshot', { name: n })) { setName(''); carica() }
  }
  const confronta = async v => {
    const r = await run('compare_versions', { a: v })
    if (r) setDiff(r.result)
  }

  return (
    <div className="versions">
      <p className="hint">Keep a version before trying another direction; compare and go back whenever you like.</p>
      <div className="row">
        <input placeholder="version name" value={name} onChange={e => setName(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') salva() }} />
        <button className="primary" onClick={salva}>Save version</button>
      </div>
      {!list.length && <p className="empty">No versions yet.</p>}
      {list.map(v => (
        <div key={v.name} className="version">
          <div className="grow"><b>{v.name}</b><small>{v.time}{v.note ? ` · ${v.note}` : ''}</small></div>
          <button title="What changed since this version" onClick={() => confronta(v.name)}>Compare</button>
          <button title="Go back to this version (Ctrl+Z undoes it)" onClick={() => run('restore_snapshot', { name: v.name })}><Icon name="history" size={14} /></button>
          <button className="icon-btn" title="Delete version" onClick={() => run('delete_snapshot', { name: v.name }).then(carica)}><Icon name="trash" size={14} /></button>
        </div>))}
      {diff && <div className="diff" onClick={() => setDiff(null)} title="Click to close">
        <b>{diff.a} → {diff.b}</b>
        {diff.same ? <p className="hint">No differences.</p> : <ul>
          {Object.entries(diff.song || {}).map(([k, [x, y]]) => <li key={k}>{k}: {String(x)} → {String(y)}</li>)}
          {diff.lufs && <li>loudness {diff.lufs[0]} → {diff.lufs[1]} LUFS</li>}
          {diff.added.length > 0 && <li>Added: {diff.added.join(', ')}</li>}
          {diff.removed.length > 0 && <li>Removed: {diff.removed.join(', ')}</li>}
          {diff.changed.map(c => <li key={c.track}>{c.track}: {c.fields.join(', ')} ({c.notes[0]} → {c.notes[1]} notes)</li>)}
          {diff.sections && <li>Sections: {diff.sections[0].join(' ')} → {diff.sections[1].join(' ')}</li>}
        </ul>}
      </div>}
    </div>
  )
}
