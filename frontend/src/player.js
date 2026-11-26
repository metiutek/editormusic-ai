// Riproduzione: il server renderizza la canzone (lo stesso codice dell'export),
// il browser la suona con WebAudio. Ogni revisione ha il suo audio in cache;
// se la canzone cambia mentre suona si ricarica e riparte dallo stesso punto.

export class Player {
  constructor() {
    this.ctx = null
    this.src = null
    this.buffers = new Map()
    this.rev = null
    this.startedAt = 0
    this.offset = 0
    this.playing = false
    this.loop = null        // [inizio, fine] in secondi
    this.loading = false
    this.onState = () => {}
  }

  _ctx() {
    if (!this.ctx) this.ctx = new (window.AudioContext || window.webkitAudioContext)()
    return this.ctx
  }

  async buffer(rev) {
    if (this.buffers.has(rev)) return this.buffers.get(rev)
    this.loading = true
    this.onState()
    try {
      const res = await fetch(`/api/audio?rev=${rev}`)
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`)
      const data = await res.arrayBuffer()
      const buf = await this._ctx().decodeAudioData(data)
      // tiene solo le ultime revisioni: l'audio pesa
      if (this.buffers.size >= 4) this.buffers.delete(this.buffers.keys().next().value)
      this.buffers.set(rev, buf)
      return buf
    } finally {
      this.loading = false
      this.onState()
    }
  }

  position() {
    if (!this.playing || !this.ctx) return this.offset
    let t = this.offset + (this.ctx.currentTime - this.startedAt)
    if (this.loop && t > this.loop[1]) {
      const L = this.loop[1] - this.loop[0]
      t = this.loop[0] + ((t - this.loop[0]) % L)
    }
    return t
  }

  _start(buf, at) {
    const ctx = this._ctx()
    if (this.src) { try { this.src.onended = null; this.src.stop() } catch { /* */ } }
    const src = ctx.createBufferSource()
    src.buffer = buf
    if (this.loop) {
      src.loop = true
      src.loopStart = this.loop[0]
      src.loopEnd = Math.min(this.loop[1], buf.duration)
      if (at < this.loop[0] || at >= this.loop[1]) at = this.loop[0]
    }
    src.connect(ctx.destination)
    src.onended = () => { if (this.src === src) { this.playing = false; this.offset = 0; this.onState() } }
    src.start(0, Math.max(0, Math.min(at, buf.duration - 0.01)))
    this.src = src
    this.startedAt = ctx.currentTime
    this.offset = at
    this.playing = true
    this.onState()
  }

  async play(rev, at = this.offset) {
    this.rev = rev
    await this._ctx().resume()
    const buf = await this.buffer(rev)
    if (rev !== this.rev) return
    this._start(buf, at)
  }

  stop(reset = false) {
    const p = this.position()
    if (this.src) { try { this.src.onended = null; this.src.stop() } catch { /* */ } }
    this.src = null
    this.playing = false
    this.offset = reset ? 0 : p
    this.onState()
  }

  seek(sec, rev) {
    this.offset = Math.max(0, sec)
    if (this.playing) this.play(rev, this.offset)
    else this.onState()
  }

  // la canzone e' cambiata: se sta suonando, nuovo audio dallo stesso punto
  async changed(rev) {
    this.rev = rev
    if (!this.playing) return
    const at = this.position()
    const buf = await this.buffer(rev)
    if (rev === this.rev && this.playing) this._start(buf, this.position() || at)
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
