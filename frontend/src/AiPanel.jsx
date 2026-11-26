// IA: cosa c'e' su questo computer, le chiavi dei servizi in rete, e le stesse
// operazioni dell'agente (generate_song, generate_audio, separate_stems,
// audio_to_midi, convert_voice). Tutto finisce su tracce nuove.
import { useEffect, useState } from 'react'
import { api } from './api.js'
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

export default function AiPanel({ project, selection, run }) {
  const [st, setSt] = useState(null)
  const [aperto, setAperto] = useState(false)
  const [song, setSong] = useState({ prompt: '', lyrics: '', seconds: '', instrumental: false, backend: 'auto' })
  const [snd, setSnd] = useState({ prompt: '', bars: 4, backend: 'auto' })
  const [voce, setVoce] = useState({ model: '', pitch: 0 })
  const [lavoro, setLavoro] = useState('')
  const carica = () => api('/api/ai').then(s => { setSt(s); setVoce(v => ({ ...v, model: v.model || s.voice.models?.[0] || '' })) }).catch(() => {})
  useEffect(() => { carica() }, [])

  const clip = selection?.kind === 'clip' ? project.tracks.flatMap(t => t.clips.map(c => ({ ...c, kind: t.kind }))).find(c => c.id === selection.id) : null
  const audio = clip && clip.kind === 'audio' ? clip : null
  const vai = async (nome, body, etichetta) => {
    setLavoro(etichetta)
    await run(nome, body)
    setLavoro('')
  }
  const haSezioniTesto = project.sections.some(s => s.lyrics)

  return (
    <div className="aipanel">
      {lavoro && <p className="busy">{lavoro}… (local generation can take minutes; you can keep editing)</p>}
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
        <h4><Icon name="scissors" size={13} /> On the selected audio clip</h4>
        {!audio ? <p className="hint">Select an audio clip on the timeline (a song, a recording, a generated track).</p> : <>
          <p className="hint"><b>{audio.name}</b></p>
          <div className="row wrap">
            <button disabled={!!lavoro || !st?.stems.ok} title={st?.stems.hint} onClick={() => vai('separate_stems', { clip: audio.id }, 'Separating stems')}>Split into 4 stems</button>
            <button disabled={!!lavoro || !st?.stems.ok} title={st?.stems.hint} onClick={() => vai('separate_stems', { clip: audio.id, two_stems: true }, 'Separating vocals')}>Vocals + backing</button>
          </div>
          <div className="row wrap">
            <button disabled={!!lavoro} title="Singing, humming, whistling, a bass or a solo → notes" onClick={() => vai('audio_to_midi', { clip: audio.id }, 'Transcribing')}>Melody → MIDI</button>
            <button disabled={!!lavoro} title="Beatbox → kick, snare, hat" onClick={() => vai('audio_to_midi', { clip: audio.id, mode: 'drums' }, 'Transcribing')}>Beatbox → drums</button>
          </div>
          <div className="row wrap">
            <select value={voce.model} onChange={e => setVoce({ ...voce, model: e.target.value })} disabled={!st?.voice.models?.length}>
              {(st?.voice.models || []).map(m => <option key={m}>{m}</option>)}
              {!st?.voice.models?.length && <option value="">no voice models</option>}</select>
            <label className="mini">Pitch <input type="number" min={-24} max={24} value={voce.pitch} onChange={e => setVoce({ ...voce, pitch: e.target.value })} /></label>
            <button disabled={!!lavoro || !voce.model} title="Re-sing this vocal with your voice (Applio)"
              onClick={() => vai('convert_voice', { clip: audio.id, model: voce.model, pitch: Number(voce.pitch) }, 'Converting the voice')}>My voice</button>
          </div>
          <p className="hint">Results go on new tracks; the original clip is muted, not deleted.</p>
        </>}
      </section>

      <section>
        <h4>Available here <button className="link" onClick={carica}>refresh</button></h4>
        {!st ? <p className="hint">checking…</p> : <>
          <Riga ok={st.comfyui.ok} label="ComfyUI">{st.comfyui.ok ? st.comfyui.url : 'not running'}</Riga>
          {st.comfyui.ok && <>
            <Riga ok={!!st.comfyui.song_model} label="Songs (ACE-Step 1.5)">{st.comfyui.song_model || 'model missing'}</Riga>
            {st.comfyui.song_hint && <p className="hint">{st.comfyui.song_hint}</p>}
            <Riga ok={!!st.comfyui.audio_model} label="Sounds (Stable Audio)">{st.comfyui.audio_model || 'model missing'}</Riga>
            {st.comfyui.audio_hint && <p className="hint">{st.comfyui.audio_hint}</p>}
          </>}
          {!st.comfyui.ok && <p className="hint">{st.comfyui.hint}</p>}
          <Riga ok={st.stems.ok} label="Stems (Demucs)">{st.stems.ok ? 'ready' : 'not installed'}</Riga>
          {!st.stems.ok && <p className="hint">{st.stems.hint}</p>}
          <Riga ok={st.voice.ok} label="Voice (Applio)">{st.voice.ok ? st.voice.models.join(', ') : 'not found'}</Riga>
          <Riga ok label="Audio → MIDI">built in</Riga>
          <button className="link" onClick={() => setAperto(!aperto)}><Icon name="gear" size={13} /> Online services (API keys)</button>
          {aperto && <Servizi st={st.cloud} onSaved={c => setSt(s => ({ ...s, cloud: c }))} />}
        </>}
      </section>
    </div>
  )
}
