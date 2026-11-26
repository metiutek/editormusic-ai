// Assistente: chiede in parole, lavora con le stesse operazioni dei pulsanti.
import { useEffect, useRef, useState } from 'react'
import { api, chatStream } from './api.js'
import { Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'
import { daVista } from './util.js'

const LIVELLI = [
  { id: 'editor', nome: 'Only the editor',
    desc: 'medit tools, plus reading files, web pages and web search.' },
  { id: 'estensioni', nome: 'Editor + my skills and MCP servers',
    desc: 'Your skills, MCP servers, plugins and Chrome. With Claude Code, safe actions run on their own and risky ones are refused.' },
  { id: 'completo', nome: 'Full access to this computer',
    desc: 'Claude Code with no permission prompts: commands, files, computer and browser control. Only if you trust what you ask it.' },
]

// A cosa arriva l'assistente oltre all'editor (llm.ACCESSI): con Claude Code
// decide le opzioni con cui parte, con i modelli via API medit collega i server
// MCP locali e passa le skill (estensioni.py).
function Accesso({ claudeCode }) {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const [collegando, setCollegando] = useState(false)
  useEffect(() => { api('/api/estensioni').then(setSt).catch(e => setErr(e.message)) }, [])
  if (!st) return err ? <p className="warn">{err}</p> : null
  const imposta = body => api('/api/estensioni', { body }).then(setSt).catch(e => setErr(e.message))
  const server = Array.isArray(st.server) ? st.server : []
  const skill = Array.isArray(st.skill) ? st.skill : []
  const spenti = server.filter(x => !x.on).map(x => x.name)
  const commuta = nome => imposta({ server_spenti: spenti.includes(nome) ? spenti.filter(n => n !== nome) : [...spenti, nome] })
  const collega = async () => {
    setCollegando(true)
    try { setSt(await api('/api/estensioni/collega', { body: {} })) } catch (e) { setErr(e.message) } finally { setCollegando(false) }
  }
  return (
    <div className="accesso">
      <h5>What the assistant can use</h5>
      {LIVELLI.map(l => (
        <button key={l.id} className={'opzione' + (st.accesso === l.id ? ' on' : '')} onClick={() => imposta({ accesso: l.id })}>
          <span className="spunta" /><span className="otesto"><b>{l.nome}</b><small>{l.desc}</small></span>
        </button>))}
      {st.accesso === 'completo' && <p className="warn">
        The assistant can run commands and change files anywhere on this computer without asking.
        {!claudeCode && ' This level needs Claude Code as the model: API models get skills and MCP servers only.'}</p>}
      {st.accesso !== 'editor' && <>
        <p className="hint">{skill.length} skills{skill.length ? `: ${skill.slice(0, 12).map(x => x.name).join(', ')}${skill.length > 12 ? '…' : ''}` : ''}</p>
        {server.map(x => (
          <label key={x.name} className="serverriga" title={x.errore || ''}>
            <input type="checkbox" checked={x.on} onChange={() => commuta(x.name)} />
            <span className={'dot' + (x.ok ? ' ok' : '')} /><span className="grow">{x.name}</span>
            <small>{x.ok ? `${x.strumenti} tools` : x.errore ? 'not connected' : x.origin}</small>
          </label>))}
        {claudeCode
          ? <p className="hint">Claude Code loads these itself, together with your claude.ai connectors and Chrome.</p>
          : <div className="row"><button disabled={collegando} onClick={collega}>{collegando ? 'Connecting…' : 'Connect MCP servers now'}</button></div>}
      </>}
      {err && <p className="warn">{err}</p>}
    </div>
  )
}

function Settings({ llm, onSaved }) {
  const [pid, setPid] = useState(llm?.provider || 'claude_code')
  const p = llm?.providers?.find(x => x.id === pid)
  const [key, setKey] = useState('')
  const [model, setModel] = useState(p?.modello || '')
  const [url, setUrl] = useState(p?.indirizzo || '')
  useEffect(() => { setModel(p?.modello || ''); setUrl(p?.indirizzo || ''); setKey('') }, [pid])
  const save = async () => {
    const r = await api('/api/llm', { body: { provider: pid, key: key || null, model, url: p?.indirizzo_modificabile ? url : null } })
    onSaved(r)
  }
  return (
    <div className="llm-settings">
      <label className="numfield wide"><span>Model</span>
        <select value={pid} onChange={e => setPid(e.target.value)}>
          {llm?.providers?.map(x => <option key={x.id} value={x.id}>{x.nome}{x.pronto ? ' ✓' : ''}</option>)}
        </select></label>
      {p?.nota && <p className="hint">{p.nota}</p>}
      {p?.vuole_chiave && <label className="numfield wide"><span>API key</span>
        <input type="password" placeholder={p.chiave || 'paste the key'} value={key} onChange={e => setKey(e.target.value)} /></label>}
      {p?.indirizzo_modificabile && <label className="numfield wide"><span>Address</span>
        <input value={url} onChange={e => setUrl(e.target.value)} /></label>}
      <label className="numfield wide"><span>Model id</span>
        <input list="modelli" value={model} onChange={e => setModel(e.target.value)} placeholder="default" />
        <datalist id="modelli">{p?.modelli?.map(m => <option key={m} value={m} />)}</datalist></label>
      {p && !p.pronto && <p className="warn">{p.motivo}</p>}
      <button className="primary" onClick={save}>Use this model</button>
      <Accesso claudeCode={(llm?.provider || pid) === 'claude_code'} />
    </div>
  )
}

const NOMI_SFORZO = { low: 'low', medium: 'medium', high: 'high', xhigh: 'extra high', max: 'max' }

// Cambio rapido di modello e sforzo del motore attivo: la conversazione resta.
function MenuModello({ llm, onChanged, onSettings }) {
  const [libero, setLibero] = useState('')
  const [err, setErr] = useState('')
  const imposta = body => api('/api/llm/rapido', { body }).then(onChanged).catch(e => setErr(e.message))
  return (
    <div className="menumodello">
      <h5>Model</h5>
      <div className="scelte">
        {(llm.modelli || []).map(m => (
          <button key={m || 'default'} className={'scelta' + ((llm.model || '') === m ? ' on' : '')} onClick={() => imposta({ modello: m })}>{m || 'default'}</button>))}
        <input placeholder="other model id" value={libero} onChange={e => setLibero(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && libero.trim()) { imposta({ modello: libero.trim() }); setLibero('') } }} />
      </div>
      {llm.sforzi?.length > 0 && <>
        <h5>Effort</h5>
        <p className="hint">How much it thinks before acting. A whole song wants high or more.</p>
        <div className="scelte">
          <button className={'scelta' + (!llm.sforzo ? ' on' : '')} onClick={() => imposta({ sforzo: '' })}>default</button>
          {llm.sforzi.map(x => <button key={x} className={'scelta' + (llm.sforzo === x ? ' on' : '')} onClick={() => imposta({ sforzo: x })}>{NOMI_SFORZO[x] || x}</button>)}
        </div>
      </>}
      {err && <p className="warn">{err}</p>}
      <button className="link" onClick={onSettings}><Icon name="gear" size={13} /> All model settings</button>
    </div>
  )
}

// Memoria comune a tutti i documenti (memoria.py): la scrivono l'assistente e
// l'agente MCP, qui si legge e si corregge a mano. E' un file Markdown.
function EditorMemoria({ onClose }) {
  const [testo, setTesto] = useState(null)
  const [file, setFile] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { api('/api/memoria').then(r => { setTesto(r.testo); setFile(r.file) }).catch(e => setErr(e.message)) }, [])
  const salva = async () => {
    try { await api('/api/memoria', { method: 'PUT', body: { testo } }); onClose() } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="Memory across songs" onClose={onClose}>
      <p className="hint">Preferences the assistant keeps for every song: usual tempos and genres, sounds and chains you
        like or hate, master loudness. It adds them when you state one; edit or delete lines freely. Stays on this computer{file ? ` (${file})` : ''}.</p>
      <textarea className="memoria-testo" value={testo ?? 'loading…'} disabled={testo === null} spellCheck={false}
        onChange={e => setTesto(e.target.value)} placeholder={'## preferences\n- my beats are 140 BPM'} />
      {err && <p className="warn">{err}</p>}
      <div className="modal-foot">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={testo === null} onClick={salva}>Save</button>
      </div>
    </Modal>
  )
}

export default function Chat({ llm, setLlm, refsSel, docPath }) {
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [refs, setRefs] = useState([])
  const [showSettings, setShowSettings] = useState(!llm?.ok)
  const [menu, setMenu] = useState(false)
  const [memoria, setMemoria] = useState(false)
  const [sopra, setSopra] = useState(false)
  const [errAll, setErrAll] = useState('')
  const fileRef = useRef(null)
  const endRef = useRef(null)
  // file allegati: copiati accanto alla canzone, all'assistente arriva il percorso (e il testo dei .txt)
  const allega = async lista => {
    const files = [...(lista || [])]
    if (!files.length) return
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    try {
      const r = await api('/api/chat/allega', { body: fd })
      setRefs(x => [...x, ...r.files])
      setErrAll('')
    } catch (e) { setErrAll(e.message) }
  }
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [msgs])
  // ogni documento ha la sua chat, salvata accanto al file: riaprendolo torna
  useEffect(() => {
    let vivo = true
    api('/api/chat/storia').then(r => { if (vivo) setMsgs(daVista(r?.vista)) }).catch(() => {})
    return () => { vivo = false }
  }, [docPath])

  const push = ev => setMsgs(m => {
    const last = m[m.length - 1]
    if (ev.type === 'text') {
      if (last?.role === 'assistant' && last.kind === 'text') return [...m.slice(0, -1), { ...last, text: last.text + ev.text }]
      return [...m, { role: 'assistant', kind: 'text', text: ev.text }]
    }
    if (ev.type === 'tool') return [...m, { role: 'tool', name: ev.name, input: ev.input, status: 'run' }]
    if (ev.type === 'tool_done' || ev.type === 'tool_error') {
      const i = m.map(x => x.role === 'tool' && x.name === ev.name && x.status === 'run').lastIndexOf(true)
      if (i < 0) return m
      const c = [...m]
      c[i] = { ...c[i], status: ev.type === 'tool_done' ? 'ok' : 'err', error: ev.message }
      return c
    }
    if (ev.type === 'error') return [...m, { role: 'error', text: ev.message }]
    if (ev.type === 'note') return [...m, { role: 'note', text: ev.message }]
    if (ev.type === 'stopped') return [...m, { role: 'note', text: 'Stopped. The changes already made stay: Ctrl+Z to undo them.' }]
    return m
  })

  const send = async () => {
    const q = text.trim()
    if ((!q && !refs.length) || busy) return
    setText('')
    const domanda = q || 'Look at the attached files.'
    setMsgs(m => [...m, { role: 'user', text: domanda, refs }])
    setBusy(true)
    const r = refs
    setRefs([])
    try { await chatStream({ question: domanda, refs: r }, push) } catch (e) { push({ type: 'error', message: e.message }) }
    setBusy(false)
  }

  return (
    <div className={'chat' + (sopra ? ' drop' : '')}
      onDragOver={e => { if (e.dataTransfer.types.includes('Files')) { e.preventDefault(); e.stopPropagation(); setSopra(true) } }}
      onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setSopra(false) }}
      onDrop={e => { if (e.dataTransfer.files.length) { e.preventDefault(); e.stopPropagation(); setSopra(false); allega(e.dataTransfer.files) } }}>
      <div className="chat-top">
        <button className={'modelpill' + (llm?.ok ? '' : ' bad') + (menu ? ' on' : '')} title={llm?.motivo || 'Model and effort'}
          onClick={() => llm?.ok ? setMenu(!menu) : setShowSettings(true)}>
          <span className="dot" />{llm?.nome || 'no model'}{llm?.model ? ` · ${llm.model}` : ''}{llm?.sforzo ? ` · ${llm.sforzo}` : ''}
        </button>
        <span className="grow" />
        <button className="icon-btn" title="Memory: what the assistant remembers across all your documents" onClick={() => setMemoria(true)}><Icon name="memory" size={15} /></button>
        <button className="icon-btn" title="New conversation" onClick={() => { api('/api/chat/reset', { body: {} }); setMsgs([]) }}><Icon name="plus" size={15} /></button>
        <button className="icon-btn" title="Settings" onClick={() => setShowSettings(!showSettings)}><Icon name="gear" size={15} /></button>
      </div>
      {menu && llm?.ok && <MenuModello llm={llm} onChanged={setLlm} onSettings={() => { setMenu(false); setShowSettings(true) }} />}
      {showSettings && <Settings llm={llm} onSaved={r => { setLlm(r); if (r.ok) setShowSettings(false) }} />}
      {memoria && <EditorMemoria onClose={() => setMemoria(false)} />}
      <div className="msgs">
        {!msgs.length && <div className="hint">
          Ask in plain words: <i>“a sad lo-fi song in A minor at 80 BPM, verse and chorus”</i>,
          <i> “make the chorus bigger”</i>, <i>“the bass is muddy, fix it”</i>, <i>“write a melody for these lyrics”</i>.
          Every step lands on the tracks and undoes with Ctrl+Z.</div>}
        {msgs.map((m, i) => m.role === 'tool'
          ? <details key={i} className={'tool ' + m.status}><summary>{m.status === 'run' ? '⋯' : m.status === 'ok' ? '✓' : '✕'} {m.name}</summary>
            <pre>{JSON.stringify(m.input, null, 1)}</pre>{m.error && <p className="warn">{m.error}</p>}</details>
          : <div key={i} className={'msg ' + m.role}>{m.text}
            {m.refs?.length > 0 && <div className="refs">{m.refs.map((r, j) => <span key={j} className="tag">[{j + 1}] {r.type === 'file' ? `📎 ${r.name}` : r.type}</span>)}</div>}</div>)}
        <div ref={endRef} />
      </div>
      <div className="chat-refs">
        {(refsSel || []).map(r => <button key={r.type + (r.id || '')} title={`Point at the selected ${r.type}`}
          onClick={() => setRefs(x => [...x, r])}>+ {r.type}{r.name ? ` ${r.name}` : ''}</button>)}
        {refs.map((r, i) => <span key={i} className={'tag' + (r.type === 'file' ? ' file' : '')} title={r.path || ''}
          onClick={() => setRefs(x => x.filter((_, j) => j !== i))}>[{i + 1}] {r.type === 'file' ? `📎 ${r.name}` : r.type} ✕</span>)}
        {errAll && <span className="warn">{errAll}</span>}
      </div>
      <div className="chat-input">
        <button className="icon-btn" title="Attach files: audio, MIDI, lyrics (.txt), images — or drop / paste them here"
          onClick={() => fileRef.current?.click()}><Icon name="clip" /></button>
        <input ref={fileRef} type="file" multiple hidden
          accept=".wav,.mp3,.flac,.ogg,.aif,.aiff,.m4a,.aac,.opus,.mp4,.mov,.mkv,.webm,.mid,.midi,.txt,.md,.lrc,.srt,.json,.csv,.png,.jpg,.jpeg,.webp,.gif,.pdf"
          onChange={e => { allega(e.target.files); e.target.value = '' }} />
        <textarea rows={3} value={text} placeholder="What should the song do? (drop files here to attach them)" onChange={e => setText(e.target.value)}
          onPaste={e => { if (e.clipboardData.files.length) { e.preventDefault(); allega(e.clipboardData.files) } }}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
        {busy
          ? <button className="icon-btn big" title="Stop" onClick={() => api('/api/chat/stop', { body: {} })}><Icon name="stop" /></button>
          : <button className="icon-btn big primary" title="Send" onClick={send}><Icon name="send" /></button>}
      </div>
    </div>
  )
}
