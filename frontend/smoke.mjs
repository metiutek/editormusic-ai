// Monta la UI compilata in jsdom con un backend finto: niente schermo bianco,
// i pannelli principali ci sono. Va lanciato dopo `npm run build`.
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { JSDOM } from 'jsdom'

const dist = new URL('./dist/', import.meta.url)
const html = readFileSync(new URL('index.html', dist), 'utf8')
const js = readdirSync(new URL('assets/', dist)).find(f => f.endsWith('.js'))
assert.ok(js, 'build missing: run npm run build')

const progetto = {
  name: 'demo', bpm: 100, key: 'A', mode: 'minor', time_sig: [4, 4], swing: 0, sample_rate: 44100, bars: 4, duration_s: 9.6,
  undo: 1, redo: 0,
  sections: [{ id: 'S1', name: 'verse', bar: 1, bars: 4, lyrics: 'la la' }],
  tracks: [{ id: 'T1', name: 'Chords', kind: 'midi', instrument: 'piano', instrument_type: 'fm', instrument_params: {}, volume_db: 0,
    color: '#4f8fd9', effects: [], sends: [],
    clips: [{ id: 'C1', name: 'Chords', bar: 1, bars: 4, notes: 2, note_list: [['A3', 0, 4, 90], ['C4', 0, 4, 90]] }] }],
  master: { volume_db: 0, effects: [] },
}
const stato = {
  project: progetto, revision: 'r1', seq: 1, history: { undo: 1, redo: 0 }, home: '/tmp',
  effects: [{ name: 'eq', group: 'tone', desc: 'EQ', params: {}, automatable: [] }],
  sounds: [{ name: 'piano', type: 'fm', category: 'keys', desc: '' }], chains: [], instruments: { fm: {} },
  theory: { modes: ['major', 'minor'], chord_styles: { block: '' }, bass_styles: { root: '' }, arp_patterns: ['up'],
    drum_genres: { pop: 'pop' }, progressions: [{ name: 'axis', roman: 'I V vi IV', mood: 'pop' }] },
  chat: { ok: false, providers: [] },
}

const dom = new JSDOM(html.replace(/<script[^>]*src="[^"]*"[^>]*><\/script>/, ''), {
  url: 'http://127.0.0.1:8780/', pretendToBeVisual: true, runScripts: 'outside-only',
})
const w = dom.window
w.fetch = async url => ({ ok: true, status: 200, text: async () => JSON.stringify(String(url).includes('/api/domanda') ? {} : stato) })
w.WebSocket = class { constructor() { setTimeout(() => {}, 0) } close() {} }
w.ResizeObserver = class { observe() {} disconnect() {} }
w.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} })
const errori = []
w.addEventListener('error', e => errori.push(e.message))
w.eval(readFileSync(new URL(`assets/${js}`, dist), 'utf8'))
await new Promise(r => setTimeout(r, 300))

const testo = w.document.body.textContent
assert.deepEqual(errori, [])
assert.ok(testo.includes('Chords'), 'track not rendered')
assert.ok(testo.includes('verse'), 'sections not rendered')
for (const t of ['Inspector', 'Compose', 'AI', 'Mixer', 'Assistant', 'Versions']) assert.ok(testo.includes(t), `tab ${t} missing`)
assert.ok(w.document.querySelector('.transport .play'), 'transport missing')
assert.ok(w.document.querySelector('.clip .mininotes'), 'clip notes missing')

// doppio clic sulla clip: si apre il piano roll
w.document.querySelector('.clip').dispatchEvent(new w.MouseEvent('dblclick', { bubbles: true }))
await new Promise(r => setTimeout(r, 100))
assert.ok(w.document.querySelector('.roll .note'), 'piano roll did not open')
console.log('smoke ok')
process.exit(0)
