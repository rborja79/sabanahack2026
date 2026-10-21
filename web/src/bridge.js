/** Cliente del puente: websocket, estado del robot y comandos. */
export class Puente extends EventTarget {
  constructor () {
    super()
    this.ws = null
    this.hola = null
    this.conectado = false
    this.ultimoEstado = null
    this.tramas = 0
    this._ultimoEnvio = 0
  }

  conectar (url) {
    this.cerrar()
    this.ws = new WebSocket(url)
    this.ws.onopen = () => { this.conectado = true; this.emitir('abierto') }
    this.ws.onclose = () => { this.conectado = false; this.emitir('cerrado') }
    this.ws.onerror = () => this.emitir('error')
    this.ws.onmessage = (ev) => {
      let m
      try { m = JSON.parse(ev.data) } catch { return }
      if (m.type === 'hola') { this.hola = m; this.emitir('hola', m) }
      else if (m.type === 'estado') { this.ultimoEstado = m; this.tramas++; this.emitir('estado', m) }
      else this.emitir('aviso', m)
    }
    return this
  }

  cerrar () { if (this.ws) { try { this.ws.close() } catch {} this.ws = null } }

  emitir (tipo, detalle) { this.dispatchEvent(new CustomEvent(tipo, { detail: detalle })) }

  enviar (obj) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj))
  }

  /** Limita el envio de poses a `hz` para no saturar el enlace. */
  enviarManos (datos, hz = 30) {
    const ahora = performance.now()
    if (ahora - this._ultimoEnvio < 1000 / hz) return
    this._ultimoEnvio = ahora
    this.enviar({ type: 'manos', ...datos })
  }

  cmd (cmd, extra = {}) { this.enviar({ type: 'cmd', cmd, ...extra }) }
}
