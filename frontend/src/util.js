// Funzioni pure dell'interfaccia: provate da test-util.mjs senza browser.

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

const NOMI = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
export const pitchName = p => `${NOMI[((p % 12) + 12) % 12]}${Math.floor(p / 12) - 1}`
export const isBlack = p => [1, 3, 6, 8, 10].includes(((p % 12) + 12) % 12)

export function parsePitch(s) {
  if (typeof s === 'number') return s
  const m = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(String(s).trim())
  if (!m) return Number(s)
  const base = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1].toUpperCase()]
  return base + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0) + (Number(m[3]) + 1) * 12
}

// nomi GM della batteria (theory.DRUMS), per il piano roll di una traccia drums
export const DRUM_NAMES = {
  35: 'kick 2', 36: 'kick', 37: 'rim', 38: 'snare', 39: 'clap', 40: 'snare 2', 42: 'hat', 44: 'hat pedal',
  45: 'tom low', 46: 'hat open', 47: 'tom mid', 49: 'crash', 50: 'tom high', 51: 'ride', 53: 'ride bell',
  54: 'tambourine', 56: 'cowbell', 57: 'crash 2', 70: 'shaker', 75: 'clave',
}

// battute 1-based <-> beat 0-based
export const barToBeat = (bar, bpb) => (bar - 1) * bpb
export const beatToBar = (beat, bpb) => beat / bpb + 1
export const roundTo = (v, k = 3) => Math.round(v * 10 ** k) / 10 ** k

// aggancia alla griglia (in beat); grid 0 = libero
export function snap(beat, grid) {
  if (!grid) return roundTo(beat, 3)
  return roundTo(Math.round(beat / grid) * grid, 4)
}

// posizione leggibile: "battuta.beat" (1-based come in qualunque DAW)
export function fmtPos(beat, bpb) {
  const bar = Math.floor(beat / bpb + 1e-9)
  const b = beat - bar * bpb
  return `${bar + 1}.${Math.floor(b + 1e-9) + 1}`
}

export function fmtTime(s) {
  if (!isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const r = s - m * 60
  return `${m}:${r < 10 ? '0' : ''}${r.toFixed(1)}`
}

// note della clip ([nome, start, length, vel] come summary full) -> oggetti numerici
export function notesFromList(list) {
  return (list || []).map(([p, start, length, velocity]) => ({ pitch: parsePitch(p), start, length, velocity }))
}
export const notesToList = notes => notes.map(n => [n.pitch, roundTo(n.start, 4), roundTo(n.length, 4), n.velocity])

// la nota sotto il cursore (beat, altezza)
export function noteAt(notes, beat, pitch) {
  for (let i = notes.length - 1; i >= 0; i--) {
    const n = notes[i]
    if (n.pitch === pitch && beat >= n.start - 1e-6 && beat <= n.start + n.length + 1e-6) return i
  }
  return -1
}

// clip sotto il cursore in una riga di traccia
export function clipAt(clips, beatBars, bpb) {
  for (const c of clips || []) {
    if (beatBars >= c.bar && beatBars < c.bar + c.bars) return c
  }
  return null
}

// intervallo di uno slider per un parametro di strumento (synth.DEFAULTS non ha min/max)
const RANGES = {
  attack: [0, 4], decay: [0, 6], sustain: [0, 1], release: [0, 6], f_attack: [0, 4], f_decay: [0, 6],
  f_sustain: [0, 1], cutoff: [20, 18000], resonance: [0.3, 12], filter_env: [-6, 6], keytrack: [0, 1],
  vel_to_filter: [0, 1], osc_mix: [0, 1], pw: [0.05, 0.95], sub: [0, 1], noise: [0, 1], unison: [1, 7],
  unison_detune: [0, 60], spread: [0, 1], osc2_semi: [-24, 24], osc2_detune: [-50, 50], vibrato_rate: [0, 12],
  vibrato_depth: [0, 100], drive: [0, 1], gain_db: [-24, 12], velocity_sens: [0, 1], octave: [-3, 3], glide: [0, 0.5],
  ratio: [0.5, 16], index: [0, 10], index_decay: [0.01, 4], index_sustain: [0, 1], ratio2: [0, 20], index2: [0, 6],
  decay2: [0.005, 1], detune: [0, 30], vel_to_index: [0, 1], tremolo: [0, 1], brightness: [0, 1],
  pick_position: [0.02, 0.5], body: [0, 1], width: [0, 1], mute: [0, 1], tune: [-12, 12], kick_freq: [30, 120],
  kick_start: [60, 400], kick_decay: [0.05, 2.5], kick_click: [0, 1], kick_drive: [0, 1], kick_sweep: [0.005, 0.2],
  snare_tone: [100, 400], snare_decay: [0.05, 0.6], snare_noise: [0, 1], clap_decay: [0.05, 0.6],
  hat_decay: [0.01, 0.2], hat_open_decay: [0.1, 1.2], hat_tone: [0, 1], tom_decay: [0.05, 1], cymbal_decay: [0.3, 4],
  crush: [0, 1], pan_spread: [0, 1], root: [24, 96], start: [0, 10], end: [0, 30],
}
export function rangeFor(name, def) {
  if (RANGES[name]) return RANGES[name]
  if (typeof def === 'number') return [Math.min(0, def * 2), Math.max(1, def * 2)]
  return [0, 1]
}

export function stepFor(p) {
  if (p.type === 'int') return 1
  const span = (p.max ?? 1) - (p.min ?? 0)
  if (span <= 2) return 0.01
  if (span <= 30) return 0.1
  return 1
}

export const fmtNum = v => (typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(0) : (+v.toFixed(3)).toString()) : String(v))
export const titleCase = s => (s || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())

// forme pronte per "structure"
export const FORMS = {
  'Pop song': [['intro', 4], ['verse', 8], ['chorus', 8], ['verse', 8], ['chorus', 8], ['bridge', 8], ['chorus', 8], ['outro', 4]],
  'EDM': [['intro', 8], ['build', 8], ['drop', 16], ['break', 8], ['build', 8], ['drop', 16], ['outro', 8]],
  'Hip-hop': [['intro', 4], ['verse', 16], ['hook', 8], ['verse', 16], ['hook', 8], ['outro', 4]],
  'Short loop': [['loop', 8]],
}

// La conversazione salvata (api._in_vista) nella forma dei messaggi della chat.
export function daVista(vista) {
  const out = []
  for (const t of vista || []) {
    if (t.role === 'user') { out.push({ role: 'user', text: t.text, refs: t.refs }); continue }
    for (const x of t.tools || []) out.push({ role: 'tool', name: x.name, input: x.input, status: x.state === 'run' ? 'err' : x.state, error: x.message })
    if (t.text) out.push({ role: 'assistant', kind: 'text', text: t.text })
    if (t.error) out.push({ role: 'error', text: t.error })
    if (t.note) out.push({ role: 'note', text: t.note })
  }
  return out
}

// classi di altezza della scala (per evidenziare le righe del piano roll)
const SCALE = {
  major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10], harmonic_minor: [0, 2, 3, 5, 7, 8, 11],
  melodic_minor: [0, 2, 3, 5, 7, 9, 11], dorian: [0, 2, 3, 5, 7, 9, 10], phrygian: [0, 1, 3, 5, 7, 8, 10],
  lydian: [0, 2, 4, 6, 7, 9, 11], mixolydian: [0, 2, 4, 5, 7, 9, 10], locrian: [0, 1, 3, 5, 6, 8, 10],
  pentatonic_major: [0, 2, 4, 7, 9], pentatonic_minor: [0, 3, 5, 7, 10], blues: [0, 3, 5, 6, 7, 10],
  chromatic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
}
export function scalePcs(key, mode) {
  const root = { C: 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, F: 5, 'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11 }[key] ?? 0
  return (SCALE[mode] || SCALE.major).map(i => (root + i) % 12)
}
