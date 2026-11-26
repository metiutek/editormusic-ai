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
    this.deviceId = ''
    this.monitor = { on: false, reverb: false, volume: 0.8 }
    this.calibrated = null          // latenza misurata (s), se c'e'
    try {
      const m = JSON.parse(localStorage.getItem('medit.rec') || '{}')
      this.deviceId = m.deviceId || ''
      Object.assign(this.monitor, m.monitor || {})
      this.calibrated = typeof m.calibrated === 'number' ? m.calibrated : null
    } catch { /* default */ }
  }

  _salva() {
    try { localStorage.setItem('medit.rec', JSON.stringify({ deviceId: this.deviceId, monitor: this.monitor, calibrated: this.calibrated })) } catch { /* */ }
  }

  get isOpen() { return !!this.stream }

  // ingressi audio (i nomi compaiono dopo il primo permesso al microfono)
  static async devices() {
    try {
      const l = await navigator.mediaDevices.enumerateDevices()
      return l.filter(d => d.kind === 'audioinput').map(d => ({ id: d.deviceId, name: d.label || 'Microphone' }))
    } catch { return [] }
  }

  async setDevice(id) {
    this.deviceId = id
    this._salva()
    if (this.stream && !this.recording) { this.close(); await this.open() }
  }

  // picco dell'ingresso adesso (0..1), anche quando non si registra
  peak() {
    if (!this.analyser) return 0
    const a = this.buf || (this.buf = new Float32Array(this.analyser.fftSize))
    this.analyser.getFloatTimeDomainData(a)
    let p = 0
    for (let i = 0; i < a.length; i++) { const v = Math.abs(a[i]); if (v > p) p = v }
    return p
  }

  // ascoltarsi in cuffia mentre si canta (con un po' di riverbero, se si vuole)
  setMonitor(ch) {
    Object.assign(this.monitor, ch)
    this._salva()
    this._monitorGraph()
  }

  _monitorGraph() {
    if (!this.src) return
    const ctx = this.ctxFn()
    if (!this.monGain) {
      this.monGain = ctx.createGain()
      this.monGain.connect(ctx.destination)
      this.monRev = ctx.createConvolver()
      // risposta all'impulso: rumore che decade in ~1.6 s, stereo
      const n = Math.floor(ctx.sampleRate * 1.6)
      const ir = ctx.createBuffer(2, n, ctx.sampleRate)
      for (let c = 0; c < 2; c++) {
        const d = ir.getChannelData(c)
        for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3)
      }
      this.monRev.buffer = ir
      this.monRevGain = ctx.createGain()
      this.monRev.connect(this.monRevGain).connect(this.monGain)
      this.src.connect(this.monGain)
      this.src.connect(this.monRev)
    }
    this.monGain.gain.value = this.monitor.on ? this.monitor.volume : 0
    this.monRevGain.gain.value = this.monitor.reverb ? 0.35 : 0
  }

  // Chiede il microfono e prepara il nodo; non registra ancora.
  async open() {
    if (this.stream) return
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot record audio (needs https or localhost)')
    const ctx = this.ctxFn()
    await ctx.resume()
    const audio = { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    if (this.deviceId) audio.deviceId = { exact: this.deviceId }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio })
    } catch (e) {
      if (!this.deviceId || e.name !== 'OverconstrainedError') throw e
      this.deviceId = ''                       // l'ingresso salvato non c'e' piu'
      delete audio.deviceId
      this.stream = await navigator.mediaDevices.getUserMedia({ audio })
    }
    if (!moduloCaricato || moduloCaricato.ctx !== ctx) {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
      moduloCaricato = { ctx, p: ctx.audioWorklet.addModule(url) }
    }
    await moduloCaricato.p
    this.src = ctx.createMediaStreamSource(this.stream)
    this.analyser = ctx.createAnalyser()
    this.analyser.fftSize = 1024
    this.src.connect(this.analyser)
    this._monitorGraph()
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

  // Ferma e restituisce { channels, sampleRate, startTime: secondi di contesto del primo campione, seconds }.
  // keepOpen: il microfono resta aperto (meter e monitoraggio continuano).
  async stop(keepOpen = false) {
    this.recording = false
    const ctx = this.ctxFn()
    this.node.port.postMessage('stop')
    await new Promise(res => setTimeout(res, 120))   // l'ultimo pezzo arriva subito dopo lo stop
    if (keepOpen) this._nuovoNodo()
    else this.close()
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
    if (this.calibrated !== null) return this.calibrated
    const ctx = this.ctxFn()
    const inp = this.stream?.getAudioTracks?.()[0]?.getSettings?.().latency || 0
    return (ctx.outputLatency || 0) + (ctx.baseLatency || 0) + inp
  }

  // dopo uno stop col microfono aperto: un nodo di registrazione nuovo (il vecchio ha finito)
  _nuovoNodo() {
    const ctx = this.ctxFn()
    try { this.src.disconnect(this.node) } catch { /* */ }
    try { this.node.disconnect() } catch { /* */ }
    const vecchio = this.node.port.onmessage
    this.node = new AudioWorkletNode(ctx, 'medit-rec', { numberOfOutputs: 1 })
    this.node.connect(this.muto)
    this.node.port.onmessage = vecchio
  }

  // Calibrazione: 4 click dagli altoparlanti, il microfono li riascolta. La differenza tra
  // quando partono e quando rientrano e' la latenza di andata e ritorno.
  async calibrate() {
    await this.open()
    const ctx = this.ctxFn()
    const sr = ctx.sampleRate
    this.start()
    const t0 = ctx.currentTime + 0.3
    const passo = 0.5
    for (let i = 0; i < 4; i++) {
      const o = ctx.createOscillator(), g = ctx.createGain()
      o.frequency.value = 1000
      g.gain.setValueAtTime(0.9, t0 + i * passo)
      g.gain.exponentialRampToValueAtTime(0.001, t0 + i * passo + 0.02)
      o.connect(g).connect(ctx.destination)
      o.start(t0 + i * passo); o.stop(t0 + i * passo + 0.03)
    }
    await new Promise(r => setTimeout(r, (0.3 + 4 * passo + 0.4) * 1000))
    const res = await this.stop(true)
    const x = res.channels[0]
    const misure = []
    for (let i = 0; i < 4; i++) {
      const a = Math.floor((t0 + i * passo - res.startTime) * sr)
      const b = Math.min(x.length, a + Math.floor(passo * 0.9 * sr))
      let mx = 0
      for (let k = Math.max(0, a); k < b; k++) mx = Math.max(mx, Math.abs(x[k]))
      if (mx < 0.02) continue
      for (let k = Math.max(0, a); k < b; k++) if (Math.abs(x[k]) > mx * 0.5) { misure.push((k - a) / sr); break }
    }
    if (misure.length < 3) throw new Error('Calibration failed: the microphone did not hear the clicks. Use the speakers (not headphones), turn them up and retry.')
    misure.sort((p, q) => p - q)
    this.calibrated = misure[Math.floor(misure.length / 2)]
    this._salva()
    return this.calibrated
  }

  resetCalibration() { this.calibrated = null; this._salva() }

  close() {
    try { this.src?.disconnect() } catch { /* */ }
    try { this.node?.disconnect() } catch { /* */ }
    try { this.muto?.disconnect() } catch { /* */ }
    try { this.monGain?.disconnect(); this.monRev?.disconnect() } catch { /* */ }
    this.stream?.getTracks().forEach(t => t.stop())
    this.stream = null
    this.node = null
    this.src = null
    this.analyser = null
    this.monGain = null
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
