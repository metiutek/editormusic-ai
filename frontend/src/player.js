// Riproduzione: il server renderizza la canzone a pezzi (lo stesso codice dell'export),
// il browser li suona in coda con WebAudio. Parte subito e, se la canzone cambia mentre
// suona, si rifanno solo i pezzi da qui in avanti.

const CHUNK = 3.0        // secondi per pezzo
const LOOKAHEAD = 4.0    // quanto audio tenere pronto davanti al cursore

export class Player {
  constructor() {
    this.ctx = null
    this.rev = null
    this.startedAt = 0
    this.offset = 0
    this.playing = false
    this.loop = null        // [inizio, fine] in secondi
    this.loading = false
    this.onState = () => {}
    this.frames = new Set()   // chi disegna il cursore: aggiornato fuori da React
    this.raf = 0
    // metronomo: suona in riproduzione e in registrazione (non finisce nel mix)
    this.metro = { on: false, sound: 'click', volume: 0.6, countIn: 1 }
    try { Object.assign(this.metro, JSON.parse(localStorage.getItem('medit.metro') || '{}')) } catch { /* default */ }
    this.tempo = { spb: 0.5, bpb: 4 }
    this.metroTimer = 0
    this.metroNext = 0
    // riproduzione a pezzi
    this.segs = []            // pezzi in coda: {src, g, gen, c0, c1, songStart}
    this.gen = 0              // cresce a ogni ripartenza o modifica: i pezzi vecchi si riconoscono
    this.pump = 0
    this.inflight = false
    this.latenza = 0.3        // quanto ci mette il server a dare un pezzo (media mobile, s)
    this.songEnd = Infinity
    this.cursor = 0           // prossimo istante della canzone da chiedere
    this.cursorCtx = 0        // e quando deve suonare, nel tempo del contesto audio
  }

  setSongEnd(sec) { this.songEnd = sec }

  setMetro(ch) {
    Object.assign(this.metro, ch)
    try { localStorage.setItem('medit.metro', JSON.stringify(this.metro)) } catch { /* solo per ora */ }
    this._metroRestart()
    this.onState()
  }

  setTempo(spb, bpb) { this.tempo = { spb, bpb } }

  // un colpo a un istante del contesto; accent = primo tempo della battuta
  click(at, accent) {
    const ctx = this._ctx()
    const g = ctx.createGain()
    const v = this.metro.volume * (accent ? 1 : 0.6)
    g.connect(ctx.destination)
    const snd = this.metro.sound
    if (snd === 'hihat') {
      const n = Math.floor(ctx.sampleRate * 0.05)
      const b = ctx.createBuffer(1, n, ctx.sampleRate)
      const d = b.getChannelData(0)
      for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.exp(-i / (n / 6))
      const s = ctx.createBufferSource()
      const hp = ctx.createBiquadFilter()
      hp.type = 'highpass'; hp.frequency.value = accent ? 6000 : 8000
      s.buffer = b
      s.connect(hp).connect(g)
      g.gain.value = v * 0.8
      s.start(at)
      return
    }
    const o = ctx.createOscillator()
    const [f, len, tipo] = { click: [accent ? 1600 : 1100, 0.03, 'square'], tick: [accent ? 2600 : 2000, 0.012, 'sine'],
      clave: [accent ? 2500 : 2000, 0.05, 'triangle'] }[snd] || [1500, 0.03, 'square']
    o.type = tipo
    o.frequency.value = f
    g.gain.setValueAtTime(0, at)
    g.gain.linearRampToValueAtTime(v * (tipo === 'square' ? 0.35 : 0.8), at + 0.001)
    g.gain.exponentialRampToValueAtTime(0.0001, at + len)
    o.connect(g)
    o.start(at)
    o.stop(at + len + 0.01)
  }

  // count-in: n battute di click, risolve quando parte il primo tempo della canzone
  countIn(bars, onBeat) {
    const ctx = this._ctx()
    const { spb, bpb } = this.tempo
    const n = Math.round(bars * bpb)
    if (!n) return Promise.resolve()
    const t0 = ctx.currentTime + 0.08
    for (let i = 0; i < n; i++) this.click(t0 + i * spb, i % bpb === 0)
    return new Promise(res => {
      let k = 0
      const tick = () => {
        const left = n - Math.floor((ctx.currentTime - t0) / spb)
        if (left !== k) { k = left; onBeat?.(Math.max(0, left)) }
        if (ctx.currentTime >= t0 + n * spb - 0.03) res()
        else setTimeout(tick, 10)
      }
      tick()
    })
  }

  _metroStop() { clearInterval(this.metroTimer); this.metroTimer = 0 }

  _metroRestart() {
    this._metroStop()
    if (!this.playing || !this.metro.on || this.loop) return
    const { spb } = this.tempo
    this.metroNext = Math.ceil((this.position() - 0.005) / spb)
    const tick = () => {
      if (!this.playing) return this._metroStop()
      const ctx = this.ctx
      // tempi che cadono nei prossimi 120 ms, programmati sul clock audio
      while (true) {
        const songT = this.metroNext * this.tempo.spb
        const at = this.startedAt + (songT - this.offset)
        if (at > ctx.currentTime + 0.12) break
        if (at >= ctx.currentTime - 0.01) this.click(Math.max(at, ctx.currentTime), this.metroNext % this.tempo.bpb === 0)
        this.metroNext++
      }
    }
    tick()
    this.metroTimer = setInterval(tick, 25)
  }

  // fn(secondi, playing) a ogni frame mentre suona, e una volta a ogni cambio di stato.
  // Il cursore si muove senza ridisegnare l'interfaccia.
  onFrame(fn) {
    this.frames.add(fn)
    fn(this.position(), this.playing)
    return () => this.frames.delete(fn)
  }

  _emit() {
    const t = this.position()
    for (const fn of this.frames) fn(t, this.playing)
  }

  _loop() {
    if (this.raf || typeof requestAnimationFrame === 'undefined') return
    const tick = () => {
      this._emit()
      this.raf = this.playing ? requestAnimationFrame(tick) : 0
    }
    this.raf = requestAnimationFrame(tick)
  }

  _changed() {
    this.onState()
    this._emit()
    if (this.playing) this._loop()
  }

  _ctx() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)()
    return this.ctx
  }

  // ---- riproduzione a pezzi ----
  // Il server renderizza pezzi di CHUNK secondi da dove si sta suonando (/api/chunk, lo stesso
  // codice dell'export) e qui si mettono in coda, attaccati al campione. Una modifica alla
  // canzone non ricarica niente: i pezzi futuri si rifanno e si sostituiscono con una
  // dissolvenza di 15 ms, cosi' un effetto cambiato si sente dopo pochi decimi di secondo.

  async _pezzo(start, dur) {
    const res = await fetch(`/api/chunk?start=${start.toFixed(4)}&dur=${dur.toFixed(4)}&rev=${this.rev || ''}`)
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`)
    return this._ctx().decodeAudioData(await res.arrayBuffer())
  }

  // prossimo tratto da chiedere: fino alla griglia dei CHUNK, al loop o alla fine
  _tratto(t) {
    if (this.loop && t >= this.loop[1] - 1e-4) t = this.loop[0]
    let fine = (Math.floor(t / CHUNK + 1e-6) + 1) * CHUNK
    if (fine - t < 0.5) fine += CHUNK                       // niente pezzi minuscoli
    if (this.loop && t < this.loop[1]) fine = Math.min(fine, this.loop[1])
    fine = Math.min(fine, this.songEnd)
    return [t, fine]
  }

  _metti(buf, songStart, at, fadeIn) {
    const ctx = this.ctx
    const src = ctx.createBufferSource()
    const g = ctx.createGain()
    src.buffer = buf
    src.connect(g).connect(ctx.destination)
    let off = 0
    if (at < ctx.currentTime + 0.01) {                        // arrivato tardi: si salta l'inizio, il tempo resta giusto
      off = ctx.currentTime + 0.02 - at
      at = ctx.currentTime + 0.02
    }
    if (off >= buf.duration) return null
    if (fadeIn) { g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(1, at + 0.015) }
    src.start(at, off)
    const seg = { src, g, gen: this.gen, c0: at, c1: at + buf.duration - off, songStart }
    src.onended = () => { this.segs = this.segs.filter(s => s !== seg) }
    this.segs.push(seg)
    return seg
  }

  // da `at` in poi suonano solo i pezzi nuovi: i vecchi sfumano e si fermano
  _taglia(at) {
    for (const s of this.segs) {
      if (s.gen === this.gen) continue
      if (s.c0 >= at) { try { s.src.stop() } catch { /* */ } continue }
      if (s.c1 > at) {
        s.g.gain.setValueAtTime(1, at)
        s.g.gain.linearRampToValueAtTime(0, at + 0.015)
        try { s.src.stop(at + 0.02) } catch { /* */ }
      }
    }
  }

  _pompa() {
    clearInterval(this.pump)
    const giro = async () => {
      if (!this.playing || this.inflight || !this.ctx) return
      if (this.cursor >= this.songEnd - 1e-3) {
        if (this.ctx.currentTime > this.cursorCtx + 0.05) { this.stop(true); this.offset = 0; this._changed() }
        return
      }
      if (this.cursorCtx - this.ctx.currentTime > LOOKAHEAD) return
      const gen = this.gen
      const [a, b] = this._tratto(this.cursor)
      const c = this.cursorCtx
      const nuovo = this.dopoCambio
      this.inflight = gen
      const t0 = performance.now()
      try {
        const buf = await this._pezzo(a, b - a)
        this.latenza = 0.7 * this.latenza + 0.3 * (performance.now() - t0) / 1000
        if (gen !== this.gen || !this.playing) return
        if (nuovo) { this._taglia(Math.max(c, this.ctx.currentTime + 0.02)); this.dopoCambio = false }
        this._metti(buf, a, c, nuovo)
        this.cursor = b
        this.cursorCtx = c + (b - a)
      } catch (e) {
        this.onError?.(e)
        this.stop()
      } finally {
        if (this.inflight === gen) this.inflight = false
      }
    }
    this.pump = setInterval(giro, 40)
    giro()
  }

  _fermaTutto() {
    clearInterval(this.pump)
    this.pump = 0
    for (const s of this.segs) { try { s.src.onended = null; s.src.stop() } catch { /* */ } }
    this.segs = []
    this.inflight = false
  }

  position() {
    if (!this.playing || !this.ctx) return this.offset
    let t = this.offset + (this.ctx.currentTime - this.startedAt)
    if (this.loop && t > this.loop[1] && this.offset <= this.loop[1]) {
      const L = this.loop[1] - this.loop[0]
      t = this.loop[0] + ((t - this.loop[0]) % L)
    }
    return t
  }

  // il tempo scorre senza audio (registrazione su canzone vuota): cursore e metronomo vanno avanti
  async runFree(at = this.offset) {
    const ctx = this._ctx()
    await ctx.resume()
    this._fermaTutto()
    this.gen++
    this.startedAt = ctx.currentTime
    this.offset = Math.max(0, at)
    this.playing = true
    this._changed()
    this._metroRestart()
  }

  async play(rev, at = this.offset) {
    this.rev = rev
    const ctx = this._ctx()
    await ctx.resume()
    this._fermaTutto()
    const gen = ++this.gen
    if (this.loop && (at < this.loop[0] || at >= this.loop[1])) at = this.loop[0]
    at = Math.max(0, Math.min(at, Math.max(0, this.songEnd - 0.05)))
    // il primo pezzo e' corto: il suono parte prima
    const [a, b0] = this._tratto(at)
    const b = Math.min(b0, a + 1.5)
    this.loading = true
    this.onState()
    let buf
    try { buf = await this._pezzo(a, b - a) } finally { this.loading = false; this.onState() }
    if (gen !== this.gen) return
    const t0 = ctx.currentTime + 0.03
    this.startedAt = t0
    this.offset = at
    this.playing = true
    this.cursor = b
    this.cursorCtx = t0 + (b - a)
    this.dopoCambio = false
    this._metti(buf, a, t0, false)
    this._changed()
    this._metroRestart()
    this._pompa()
  }

  stop(reset = false) {
    const p = this.position()
    this._fermaTutto()
    this.gen++
    this.playing = false
    this.offset = reset ? 0 : p
    this._metroStop()
    this._changed()
  }

  seek(sec, rev) {
    this.offset = Math.max(0, sec)
    if (this.playing) this.play(rev, this.offset)
    else this._changed()
  }

  // la canzone e' cambiata: mentre suona si rifanno solo i pezzi da qui in avanti
  async changed(rev) {
    this.rev = rev
    if (!this.playing || !this.pump) return
    this.gen++                                   // i pezzi in arrivo della versione vecchia si scartano
    const at = this.ctx.currentTime + Math.min(0.6, Math.max(0.12, this.latenza * 1.3))
    let s = this.offset + (at - this.startedAt)
    if (this.loop && s > this.loop[1] && this.offset <= this.loop[1]) s = this.loop[0] + ((s - this.loop[0]) % (this.loop[1] - this.loop[0]))
    this.cursor = s
    this.cursorCtx = at
    this.dopoCambio = true
    this.inflight = false
  }

  setLoop(loop) {
    this.loop = loop
    if (this.playing) this.play(this.rev, this.position())
  }

  async audition(track, pitch, velocity = 100) {
    try {
      const ctx = this._ctx()
      await ctx.resume()
      const res = await fetch(`/api/note?track=${encodeURIComponent(track)}&pitch=${pitch}&velocity=${velocity}`)
      if (!res.ok) return
      const buf = await ctx.decodeAudioData(await res.arrayBuffer())
      const s = ctx.createBufferSource()
      s.buffer = buf
      s.connect(ctx.destination)
      s.start()
    } catch { /* senza audio si edita lo stesso */ }
  }
}
