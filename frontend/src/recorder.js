// Registrazione dal microfono. Il segnale grezzo arriva da un AudioWorklet (niente
// compressione del browser, niente webm da convertire): alla fine diventa un WAV
// a 32 bit float allineato alla canzone, latenza compresa.

const WORKLET = `
class MeditRec extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buf = []
    this.n = 0
    this.first = -1
    this.on = true
    this.port.onmessage = e => { if (e.data === 'stop') { this.flush(); this.on = false } }
  }
  flush() {
    if (!this.n) return
    const ch = this.buf[0].length
    const out = []
    for (let c = 0; c < ch; c++) {
      const a = new Float32Array(this.n)
      let o = 0
      for (const b of this.buf) { a.set(b[c], o); o += b[c].length }
      out.push(a)
    }
    let peak = 0
    for (const a of out) for (let i = 0; i < a.length; i++) { const v = Math.abs(a[i]); if (v > peak) peak = v }
    this.port.postMessage({ first: this.first, data: out, peak }, out.map(a => a.buffer))
    this.buf = []
    this.n = 0
  }
  process(inputs) {
    const inp = inputs[0]
    if (this.on && inp && inp.length) {
      if (this.first < 0) this.first = currentFrame
      this.buf.push(inp.map(c => c.slice()))
      this.n += inp[0].length
      if (this.n >= 2048) this.flush()
    }
    return this.on
  }
}
registerProcessor('medit-rec', MeditRec)
`

let moduloCaricato = null

export class Recorder {
  constructor(ctxFn) {
    this.ctxFn = ctxFn
    this.stream = null
    this.node = null
    this.chunks = []
    this.first = -1
    this.level = 0
    this.recording = false
    this.onLevel = () => {}
  }

  // Chiede il microfono e prepara il nodo; non registra ancora.
  async open() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot record audio (needs https or localhost)')
    const ctx = this.ctxFn()
    await ctx.resume()
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    })
    if (!moduloCaricato || moduloCaricato.ctx !== ctx) {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
      moduloCaricato = { ctx, p: ctx.audioWorklet.addModule(url) }
    }
    await moduloCaricato.p
    this.src = ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(ctx, 'medit-rec', { numberOfOutputs: 1 })
    // il nodo deve stare nel grafo per girare; esce muto
    this.muto = ctx.createGain()
    this.muto.gain.value = 0
    this.node.connect(this.muto).connect(ctx.destination)
    this.node.port.onmessage = e => {
      const { first, data, peak } = e.data
      if (this.first < 0) this.first = first
      this.chunks.push(data)
      this.level = Math.max(peak, this.level * 0.6)
      this.onLevel(this.level)
    }
  }

  start() {
    this.chunks = []
    this.first = -1
    this.recording = true
    this.src.connect(this.node)
  }

  // Ferma e restituisce { wav: Blob, startTime: secondi di contesto del primo campione, seconds }
  async stop() {
    this.recording = false
    const ctx = this.ctxFn()
    this.node.port.postMessage('stop')
    await new Promise(res => setTimeout(res, 120))   // l'ultimo pezzo arriva subito dopo lo stop
    this.close()
    const sr = ctx.sampleRate
    const ch = this.chunks[0]?.length || 1
    const n = this.chunks.reduce((s, c) => s + c[0].length, 0)
    const canali = Array.from({ length: ch }, () => new Float32Array(n))
    let o = 0
    for (const c of this.chunks) {
      for (let k = 0; k < ch; k++) canali[k].set(c[k], o)
      o += c[0].length
    }
    this.chunks = []
    return { channels: canali, sampleRate: sr, startTime: this.first / sr, seconds: n / sr }
  }

  // latenza di andata e ritorno stimata: quello che si sente esce dopo, quello che si canta entra dopo
  latency() {
    const ctx = this.ctxFn()
    const inp = this.stream?.getAudioTracks?.()[0]?.getSettings?.().latency || 0
    return (ctx.outputLatency || 0) + (ctx.baseLatency || 0) + inp
  }

  close() {
    try { this.src?.disconnect() } catch { /* */ }
    try { this.node?.disconnect() } catch { /* */ }
    try { this.muto?.disconnect() } catch { /* */ }
    this.stream?.getTracks().forEach(t => t.stop())
    this.stream = null
    this.node = null
    this.level = 0
  }
}

// WAV float 32 bit, mono o stereo
export function encodeWav(channels, sampleRate) {
  const ch = channels.length
  const n = channels[0]?.length || 0
  const buf = new ArrayBuffer(44 + n * ch * 4)
  const v = new DataView(buf)
  const s = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)) }
  s(0, 'RIFF'); v.setUint32(4, 36 + n * ch * 4, true); s(8, 'WAVE')
  s(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 3, true); v.setUint16(22, ch, true)
  v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * ch * 4, true)
  v.setUint16(32, ch * 4, true); v.setUint16(34, 32, true)
  s(36, 'data'); v.setUint32(40, n * ch * 4, true)
  const out = new Float32Array(buf, 44)
  for (let i = 0; i < n; i++) for (let k = 0; k < ch; k++) out[i * ch + k] = channels[k][i]
  return new Blob([buf], { type: 'audio/wav' })
}

// toglie i primi `sec` secondi (latenza o parte prima dell'inizio della canzone)
export function trimStart(channels, sampleRate, sec) {
  const k = Math.max(0, Math.round(sec * sampleRate))
  return k ? channels.map(c => c.subarray(Math.min(k, c.length))) : channels
}
