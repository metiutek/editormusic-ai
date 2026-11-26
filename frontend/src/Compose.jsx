// Comporre a mano con gli stessi generatori dell'agente: forma, accordi, batteria,
// basso, arpeggi, melodia. Ogni pulsante e' una operazione di Store.
import { useState } from 'react'
import Icon from './Icons.jsx'
import { FORMS } from './util.js'

function F({ label, children }) {
  return <label className="field"><span>{label}</span>{children}</label>
}

export default function Compose({ project, catalog, run, playheadBar, selectedTrack }) {
  const th = catalog.theory || {}
  const [prog, setProg] = useState('vi IV I V')
  const [bar, setBar] = useState(1)
  const [bars, setBars] = useState(8)
  const [chordStyle, setChordStyle] = useState('block')
  const [chordSound, setChordSound] = useState('piano')
  const [bassStyle, setBassStyle] = useState('root')
  const [bassSound, setBassSound] = useState('saw bass')
  const [genre, setGenre] = useState('pop')
  const [intensity, setIntensity] = useState('normal')
  const [fill, setFill] = useState(4)
  const [arp, setArp] = useState('up')
  const [rate, setRate] = useState(0.25)
  const [melody, setMelody] = useState('E5:1 D5:0.5 C5:0.5 A4:2 r:1 C5:1 D5:1 E5:2')
  const [form, setForm] = useState('Pop song')
  const suoni = cat => (catalog.sounds || []).filter(s => !cat || cat.includes(s.category)).map(s => s.name)
  const dove = { bar: Number(bar), bars: Number(bars) }
  const midiSel = selectedTrack && selectedTrack.kind === 'midi' ? selectedTrack : null
  const traccia = ruolo => (midiSel && (midiSel.role === ruolo || !midiSel.role) ? { track: midiSel.id } : {})

  return (
    <div className="compose">
      <p className="hint">Key {project.key} {project.mode} · {project.bpm} BPM. New parts go on new tracks
        {midiSel ? <> (or on <b>{midiSel.name}</b> when its role matches)</> : null}.</p>
      <div className="grid2">
        <F label="From bar"><input type="number" min={1} value={bar} onChange={e => setBar(e.target.value)} /></F>
        <F label="Bars"><input type="number" min={1} value={bars} onChange={e => setBars(e.target.value)} /></F>
      </div>
      <button className="link" onClick={() => setBar(Math.floor(playheadBar))}>use the playhead bar ({Math.floor(playheadBar)})</button>

      <section>
        <h4>Song form</h4>
        <div className="row">
          <select className="grow" value={form} onChange={e => setForm(e.target.value)}>{Object.keys(FORMS).map(f => <option key={f}>{f}</option>)}</select>
          <button onClick={() => run('structure', { sections: FORMS[form].map(([name, b]) => ({ name, bars: b })) })}>Set sections</button>
        </div>
        <p className="hint">{FORMS[form].map(([n, b]) => `${n} ${b}`).join(' · ')}</p>
      </section>

      <section>
        <h4><Icon name="piano" size={13} /> Chords</h4>
        <input className="wide" value={prog} onChange={e => setProg(e.target.value)} placeholder="Am F C G · vi IV I V · | Am | F G |" />
        <div className="chips">{(th.progressions || []).slice(0, 14).map(p => (
          <button key={p.name} className="chip" title={p.mood} onClick={() => setProg(p.roman)}>{p.name}</button>))}</div>
        <div className="grid2">
          <F label="Style"><select value={chordStyle} onChange={e => setChordStyle(e.target.value)}>
            {Object.entries(th.chord_styles || {}).map(([k, d]) => <option key={k} value={k} title={d}>{k}</option>)}</select></F>
          <F label="Sound"><select value={chordSound} onChange={e => setChordSound(e.target.value)}>
            {suoni(['keys', 'pad', 'guitar', 'pluck']).map(s => <option key={s}>{s}</option>)}</select></F>
        </div>
        <button className="primary" onClick={() => run('add_chords', { progression: prog, style: chordStyle, ...dove, ...traccia('chords'), ...(traccia('chords').track ? {} : { sound: chordSound }) })}>Add chords</button>
      </section>

      <section>
        <h4><Icon name="music" size={13} /> Bass</h4>
        <p className="hint">Follows the chord progression above.</p>
        <div className="grid2">
          <F label="Style"><select value={bassStyle} onChange={e => setBassStyle(e.target.value)}>
            {Object.entries(th.bass_styles || {}).map(([k, d]) => <option key={k} value={k} title={d}>{k}</option>)}</select></F>
          <F label="Sound"><select value={bassSound} onChange={e => setBassSound(e.target.value)}>
            {suoni(['bass']).map(s => <option key={s}>{s}</option>)}</select></F>
        </div>
        <button className="primary" onClick={() => run('add_bassline', { progression: prog, style: bassStyle, ...dove, ...traccia('bass'), ...(traccia('bass').track ? {} : { sound: bassSound }) })}>Add bass line</button>
      </section>

      <section>
        <h4><Icon name="drum" size={13} /> Drums</h4>
        <div className="grid2">
          <F label="Genre"><select value={genre} onChange={e => setGenre(e.target.value)}>
            {Object.entries(th.drum_genres || {}).map(([k, d]) => <option key={k} value={k} title={d}>{k}</option>)}</select></F>
          <F label="Intensity"><select value={intensity} onChange={e => setIntensity(e.target.value)}>
            {['sparse', 'normal', 'busy'].map(x => <option key={x}>{x}</option>)}</select></F>
          <F label="Fill every (bars, 0 = none)"><input type="number" min={0} value={fill} onChange={e => setFill(e.target.value)} /></F>
        </div>
        <p className="hint">{th.drum_genres?.[genre]}</p>
        <button className="primary" onClick={() => run('add_drums', { genre, intensity, fill_every: Number(fill), ...dove, ...traccia('drums') })}>Add drums</button>
      </section>

      <section>
        <h4>Arpeggio</h4>
        <div className="grid2">
          <F label="Pattern"><select value={arp} onChange={e => setArp(e.target.value)}>{(th.arp_patterns || []).map(x => <option key={x}>{x}</option>)}</select></F>
          <F label="Rate"><select value={rate} onChange={e => setRate(Number(e.target.value))}>
            {[[0.5, '1/8'], [0.25, '1/16'], [1 / 3, '1/8 triplet'], [0.125, '1/32']].map(([v, n]) => <option key={n} value={v}>{n}</option>)}</select></F>
        </div>
        <button onClick={() => run('add_arpeggio', { progression: prog, pattern: arp, rate, ...dove, ...traccia('arp') })}>Add arpeggio</button>
      </section>

      <section>
        <h4>Melody</h4>
        <textarea rows={3} value={melody} onChange={e => setMelody(e.target.value)} />
        <p className="hint">note:beats · r = rest · [C4 E4 G4]:2 = chord · ! accent · ~ tie</p>
        <button onClick={() => run('add_melody', { melody, bar: Number(bar), ...traccia('lead') })}>Add melody</button>
      </section>
    </div>
  )
}
