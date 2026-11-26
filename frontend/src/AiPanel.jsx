// IA: cosa c'e' su questo computer, le chiavi dei servizi in rete, e le stesse
// operazioni dell'agente (generate_song, generate_audio, separate_stems con UVR o
// Demucs, voice_cover, audio_to_midi, convert_voice). Tutto finisce su tracce nuove.
// Applio si puo' anche aprire intero, dentro l'editor.
import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { Modal } from './Dialogs.jsx'
import Icon from './Icons.jsx'

function Riga({ ok, label, children }) {
  return <div className="ai-row"><span className={'dot' + (ok ? ' ok' : '')} /><b>{label}</b><span className="grow" /><small>{children}</small></div>
}

function Servizi({ st, onSaved }) {
  const [chiavi, setChiavi] = useState({})
  const [err, setErr] = useState('')
  const salva = async (service, extra = {}) => {
    try { onSaved(await api('/api/ai/services', { body: { service, key: chiavi[service] ?? null, ...extra } })); setChiavi(c => ({ ...c, [service]: undefined })) } catch (e) { setErr(e.message) }
  }
  return (
    <div className="ai-services">
      {Object.entries(st.services).map(([k, s]) => (
        <div key={k} className="ai-service">
          <div className="row"><b className="grow">{s.name}</b>{s.ready && <span className="tag">{s.key}</span>}</div>
          <p className="hint">{s.note}</p>
          <div className="row">
            <input type="password" className="grow" placeholder={s.ready ? 'replace the key' : 'paste the API key'} value={chiavi[k] || ''}
              onChange={e => setChiavi(c => ({ ...c, [k]: e.target.value }))} />
            <button disabled={!chiavi[k]} onClick={() => salva(k)}>Save</button>
          </div>
          {s.ready && <label className="check"><input type="checkbox" checked={st.default === k}
            onChange={e => salva(k, { default: e.target.checked })} /> use it when the engine is “auto” (paid per use)</label>}
        </div>))}
      <p className="hint">Keys stay on this computer (~/.medit/ai_api.json), never in the song and never through the agent.</p>
      {err && <p className="warn">{err}</p>}
    </div>
  )
}

// L'interfaccia di Applio (Gradio) avviata da medit e mostrata qui dentro
function ApplioUI({ onClose }) {
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const timer = useRef(null)
  const controlla = () => api('/api/applio').then(setSt).catch(e => setErr(e.message))
  useEffect(() => {
    api('/api/applio/start', { body: {} }).then(setSt).catch(e => setErr(e.message))
    timer.current = setInterval(controlla, 2500)
    return () => clearInterval(timer.current)
  }, [])
  useEffect(() => { if (st?.running) clearInterval(timer.current) }, [st?.running])
  return (
    <div className="applio-modal">
      <Modal title="Applio" onClose={onClose}>
        <div className="row">
          <span className="hint grow">Train voice models, text-to-speech, all of Applio. New models appear in medit by themselves.</span>
          {st?.url && <a href={st.url} target="_blank" rel="noreferrer"><button><Icon name="external" size={13} /> Open in a window</button></a>}
          {st?.started_by_medit && <button onClick={() => api('/api/applio/stop', { body: {} }).then(onClose)}>Stop Applio</button>}
        </div>
        {err && <p className="warn">{err}</p>}
        {st?.running ? <iframe src={st.url} title="Applio" />
          : !err && <p className="busy">Starting Applio… (20-60 s the first time)</p>}
      </Modal>
    </div>
  )
}

const F0 = ['rmvpe', 'crepe', 'crepe-tiny', 'fcpe', 'hybrid[rmvpe+fcpe]', 'hybrid[crepe+rmvpe]']

export default function AiPanel({ project, selection, run }) {
  const [st, setSt] = useState(null)
  const [stem, setStem] = useState(null)
  const [aperto, setAperto] = useState(false)
  const [applio, setApplio] = useState(false)
  const [song, setSong] = useState({ prompt: '', lyrics: '', seconds: '', instrumental: false, backend: 'auto' })
  const [snd, setSnd] = useState({ prompt: '', bars: 4, backend: 'auto' })
  const [sep, setSep] = useState({ engine: 'auto', model: '' })
  const [voce, setVoce] = useState({ model: '', pitch: 0, f0_method: 'rmvpe', index_rate: 0.5, protect: 0.33,
    autotune: false, clean: false, formant_shift: 0, split_audio: false })
  const [avanzate, setAvanzate] = useState(false)
  const [lavoro, setLavoro] = useState('')
  const carica = () => {
    api('/api/ai').then(s => { setSt(s); setVoce(v => ({ ...v, model: v.model || s.voice.models?.[0] || '' })) }).catch(() => {})
    api('/api/op/stem_engines', { body: {} }).then(r => setStem(r.result)).catch(() => {})
  }
  useEffect(() => { carica() }, [])

  const clip = selection?.kind === 'clip' ? project.tracks.flatMap(t => t.clips.map(c => ({ ...c, kind: t.kind }))).find(c => c.id === selection.id) : null
  const audio = clip && clip.kind === 'audio' ? clip : null
  const [t0, setT0] = useState(0)
  const [, tick] = useState(0)
  useEffect(() => {
    if (!lavoro) return
    const id = setInterval(() => tick(x => x + 1), 1000)
    return () => clearInterval(id)
  }, [lavoro])
  const vai = async (nome, body, etichetta) => {
    setLavoro(etichetta)
    setT0(Date.now())
    try { await run(nome, body) } finally { setLavoro('') }
  }
  const trascorso = Math.floor((Date.now() - t0) / 1000)
  const haSezioniTesto = project.sections.some(s => s.lyrics)
  const puoSeparare = stem && (stem.uvr.ok || stem.demucs.ok)
  const sepBody = { engine: sep.engine, ...(sep.model ? { model: sep.model } : {}) }
  const opzioniVoce = { model: voce.model, pitch: Number(voce.pitch), f0_method: voce.f0_method, index_rate: Number(voce.index_rate),
    protect: Number(voce.protect), autotune: voce.autotune, clean: voce.clean, formant_shift: Number(voce.formant_shift) }
  const hintSep = stem && !puoSeparare ? `${stem.uvr.hint}` : ''

  return (
    <div className="aipanel">
      {lavoro && <p className="busy">{lavoro}… {Math.floor(trascorso / 60)}:{String(trascorso % 60).padStart(2, '0')} (a full song can take a few minutes; you can keep editing)</p>}

      <section>
        <h4><Icon name="scissors" size={13} /> On the selected audio clip</h4>
        {!audio ? <p className="hint">Select an audio clip on the timeline (a song, a recording, a generated track) — or drop a file on the tracks.</p> : <>
          <p className="hint"><b>{audio.name}</b></p>
          <div className="row wrap">
            <select value={sep.engine} onChange={e => setSep({ ...sep, engine: e.target.value })} title="Separator">
              <option value="auto">auto</option><option value="uvr">UVR</option><option value="demucs">Demucs</option></select>
            {sep.engine !== 'demucs' && <select className="grow" value={sep.model} onChange={e => setSep({ ...sep, model: e.target.value })} title="UVR model">
              <option value="">{stem?.uvr.models?.length ? 'best vocals model on disk' : 'default (downloaded on first use)'}</option>
              {(stem?.uvr.models || []).map(m => <option key={m.name} value={m.name}>{m.name} — {m.arch}, {m.use}</option>)}
            </select>}
          </div>
          <div className="row wrap">
            <button disabled={!!lavoro || !puoSeparare} title={hintSep || 'One track per stem; the original is muted'}
              onClick={() => vai('separate_stems', { clip: audio.id, ...sepBody }, 'Separating')}>Separate</button>
            {sep.engine === 'demucs' && <button disabled={!!lavoro || !stem?.demucs.ok} onClick={() => vai('separate_stems', { clip: audio.id, engine: 'demucs', two_stems: true }, 'Separating vocals')}>Vocals + backing</button>}
            <button disabled={!!lavoro} title="Singing, humming, whistling, a bass or a solo → notes" onClick={() => vai('audio_to_midi', { clip: audio.id }, 'Transcribing')}>Melody → MIDI</button>
            <button disabled={!!lavoro} title="Beatbox → kick, snare, hat" onClick={() => vai('audio_to_midi', { clip: audio.id, mode: 'drums' }, 'Transcribing')}>Beatbox → drums</button>
          </div>
          {hintSep && <p className="hint">{hintSep}</p>}

          <h4><Icon name="music" size={13} /> Your voice (Applio)</h4>
          <div className="row wrap">
            <select value={voce.model} onChange={e => setVoce({ ...voce, model: e.target.value })} disabled={!st?.voice.models?.length}>
              {(st?.voice.models || []).map(m => <option key={m}>{m}</option>)}
              {!st?.voice.models?.length && <option value="">no voice models</option>}</select>
            <label className="mini">Pitch <input type="number" min={-24} max={24} value={voce.pitch} onChange={e => setVoce({ ...voce, pitch: e.target.value })} /></label>
            <button className="link" onClick={() => setAvanzate(!avanzate)}>{avanzate ? 'fewer options' : 'more options'}</button>
          </div>
          {avanzate && <div className="opzioni-voce">
            <div className="row wrap">
              <label className="mini">Pitch method <select value={voce.f0_method} onChange={e => setVoce({ ...voce, f0_method: e.target.value })}>
                {F0.map(f => <option key={f}>{f}</option>)}</select></label>
              <label className="mini" title="Timbre younger (+) or more mature (−) without changing the notes">Formant <input type="number" min={-12} max={12} step={0.5}
                value={voce.formant_shift} onChange={e => setVoce({ ...voce, formant_shift: e.target.value })} /></label>
            </div>
            <div className="row wrap">
              <label className="mini" title="How much of the model's accent (0-1)">Index <input type="number" min={0} max={1} step={0.05}
                value={voce.index_rate} onChange={e => setVoce({ ...voce, index_rate: e.target.value })} /></label>
              <label className="mini" title="Protect consonants and breaths (0-0.5)">Protect <input type="number" min={0} max={0.5} step={0.01}
                value={voce.protect} onChange={e => setVoce({ ...voce, protect: e.target.value })} /></label>
            </div>
            <div className="row wrap">
              <label className="check"><input type="checkbox" checked={voce.autotune} onChange={e => setVoce({ ...voce, autotune: e.target.checked })} /> autotune</label>
              <label className="check"><input type="checkbox" checked={voce.clean} onChange={e => setVoce({ ...voce, clean: e.target.checked })} /> noise reduction</label>
            </div>
          </div>}
          <div className="row wrap">
            <button disabled={!!lavoro || !voce.model} title="This clip is already a vocal: re-sing it with your voice"
              onClick={() => vai('convert_voice', { clip: audio.id, ...opzioniVoce, split_audio: voce.split_audio }, 'Converting the voice')}>Convert this vocal</button>
            <button className="primary" disabled={!!lavoro || !voce.model || !puoSeparare}
              title={hintSep || 'UVR separates vocals and backing, Applio re-sings the vocal with your voice, the backing stays'}
              onClick={() => vai('voice_cover', { clip: audio.id, ...opzioniVoce, engine: sep.engine, ...(sep.model ? { uvr_model: sep.model } : {}) }, 'Making the cover with your voice')}>
              Cover with my voice</button>
          </div>
          <p className="hint">Results go on new tracks; the original clip is muted, not deleted.</p>
        </>}
      </section>

      <section>
        <h4><Icon name="sparkle" size={13} /> Song with vocals</h4>
        <textarea rows={2} placeholder="style: genre, mood, instruments, voice — e.g. “melancholic indie pop, breathy female vocal, acoustic guitar”"
          value={song.prompt} onChange={e => setSong({ ...song, prompt: e.target.value })} />
        <textarea rows={4} disabled={song.instrumental}
          placeholder={haSezioniTesto ? 'lyrics — empty = the lyrics of your sections' : '[Verse]\nfirst line…\n\n[Chorus]\n…'}
          value={song.lyrics} onChange={e => setSong({ ...song, lyrics: e.target.value })} />
        <div className="row wrap">
          <label className="check"><input type="checkbox" checked={song.instrumental} onChange={e => setSong({ ...song, instrumental: e.target.checked })} /> instrumental</label>
          <input type="number" placeholder={project.sections.length ? 'length of the form' : 'seconds (60)'} style={{ width: 130 }}
            value={song.seconds} onChange={e => setSong({ ...song, seconds: e.target.value })} />
          <select value={song.backend} onChange={e => setSong({ ...song, backend: e.target.value })}>
            {['auto', 'comfyui', 'elevenlabs'].map(b => <option key={b}>{b}</option>)}</select>
        </div>
        <p className="hint">{project.bpm} BPM, {project.key} {project.mode} from the song.</p>
        <button className="primary" disabled={!song.prompt.trim() || !!lavoro} onClick={() => vai('generate_song', {
          prompt: song.prompt, instrumental: song.instrumental, backend: song.backend,
          ...(song.lyrics.trim() ? { lyrics: song.lyrics } : {}), ...(song.seconds ? { seconds: Number(song.seconds) } : {}),
        }, 'Generating the song')}>Generate song</button>
      </section>

      <section>
        <h4><Icon name="wave" size={13} /> Sound, loop or effect</h4>
        <input className="wide" placeholder="e.g. “dusty boom bap drum loop”, “warm vinyl crackle pad”, “cinematic riser”"
          value={snd.prompt} onChange={e => setSnd({ ...snd, prompt: e.target.value })} />
        <div className="row">
          <label className="mini">Bars <input type="number" min={1} value={snd.bars} onChange={e => setSnd({ ...snd, bars: e.target.value })} /></label>
          <select value={snd.backend} onChange={e => setSnd({ ...snd, backend: e.target.value })}>
            {['auto', 'comfyui', 'elevenlabs', 'replicate'].map(b => <option key={b}>{b}</option>)}</select>
          <button disabled={!snd.prompt.trim() || !!lavoro} onClick={() => vai('generate_audio', { prompt: snd.prompt, bars: Number(snd.bars), backend: snd.backend }, 'Generating the sound')}>Generate</button>
        </div>
      </section>

      <section>
        <h4>Available here <button className="link" onClick={carica}>refresh</button></h4>
        {!st ? <p className="hint">checking…</p> : <>
          <Riga ok={st.uvr.ok} label="Stems (UVR)">{st.uvr.ok ? `${st.uvr.models.length} models` : 'runner not installed'}</Riga>
          {!st.uvr.ok && <p className="hint">{st.uvr.hint}{st.uvr.models.length ? ` — your UVR models: ${st.uvr.models.join(', ')}` : ''}</p>}
          <Riga ok={st.stems.ok} label="Stems (Demucs)">{st.stems.ok ? 'ready' : 'not installed'}</Riga>
          <Riga ok={st.voice.ok} label="Voice (Applio)">{st.voice.ok ? st.voice.models.join(', ') : 'not found'}</Riga>
          {st.voice.path && <button onClick={() => setApplio(true)}><Icon name="external" size={13} /> Open Applio inside medit</button>}
          <Riga ok={st.comfyui.ok} label="ComfyUI">{st.comfyui.ok ? st.comfyui.url : 'not running'}</Riga>
          {st.comfyui.ok && <>
            <Riga ok={!!st.comfyui.song_model} label="Songs (ACE-Step 1.5)">{st.comfyui.song_model || 'model missing'}</Riga>
            {st.comfyui.song_hint && <p className="hint">{st.comfyui.song_hint}</p>}
            <Riga ok={!!st.comfyui.audio_model} label="Sounds (Stable Audio)">{st.comfyui.audio_model || 'model missing'}</Riga>
            {st.comfyui.audio_hint && <p className="hint">{st.comfyui.audio_hint}</p>}
          </>}
          {!st.comfyui.ok && <p className="hint">{st.comfyui.hint}</p>}
          <Riga ok label="Audio → MIDI">built in</Riga>
          <button className="link" onClick={() => setAperto(!aperto)}><Icon name="gear" size={13} /> Online services (API keys)</button>
          {aperto && <Servizi st={st.cloud} onSaved={c => setSt(s => ({ ...s, cloud: c }))} />}
        </>}
      </section>
      {applio && <ApplioUI onClose={() => { setApplio(false); carica() }} />}
    </div>
  )
}
