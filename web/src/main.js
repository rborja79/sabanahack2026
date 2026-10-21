/** Visor XR: pinta el robot, lee las manos y habla con el puente. */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { VRButton } from 'three/examples/jsm/webxr/VRButton.js'
import { ARButton } from 'three/examples/jsm/webxr/ARButton.js'
import { XRHandModelFactory } from 'three/examples/jsm/webxr/XRHandModelFactory.js'
import { Puente } from './bridge.js'
import { RobotVista, tresAmj } from './robot.js'

const $ = (id) => document.getElementById(id)

// ---------------------------------------------------------------- escena
const escena = new THREE.Scene()
escena.background = new THREE.Color(0x0b1020)

const camara = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.01, 50)
camara.position.set(1.6, 1.5, 1.9)

const render = new THREE.WebGLRenderer({ antialias: true, alpha: true })
render.setPixelRatio(Math.min(devicePixelRatio, 2))
render.setSize(innerWidth, innerHeight)
render.xr.enabled = true
render.xr.setReferenceSpaceType('local-floor')
document.body.appendChild(render.domElement)

const orbita = new OrbitControls(camara, render.domElement)
orbita.target.set(0, 0.9, 0)
orbita.enableDamping = true

escena.add(new THREE.HemisphereLight(0xdde6ff, 0x1a2140, 1.1))
const sol = new THREE.DirectionalLight(0xffffff, 1.4)
sol.position.set(2.5, 4, 2)
escena.add(sol)

// Suelo y rejilla: se esconden en AR para no tapar la camara.
const decorado = new THREE.Group()
const rejilla = new THREE.GridHelper(8, 32, 0x33406b, 0x1d2644)
decorado.add(rejilla)
const piso = new THREE.Mesh(
  new THREE.CircleGeometry(4, 48).rotateX(-Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: 0x121a33, roughness: 1 }))
piso.position.y = -0.002
decorado.add(piso)
escena.add(decorado)

// ---------------------------------------------------------------- robot
const vista = new RobotVista(escena)
const mundo = new THREE.Group()        // reubica al robot cuando se usa AR
mundo.add(vista.raiz)
escena.add(mundo)

// ---------------------------------------------------------------- manos
const LADOS = ['left', 'right']
const COLOR = { left: 0x4fd1c5, right: 0xf6ad55 }

/** Representa una mano: en escritorio es una esfera que se arrastra. */
function crearMarcador (lado) {
  const g = new THREE.Mesh(
    new THREE.SphereGeometry(0.045, 20, 16),
    new THREE.MeshStandardMaterial({ color: COLOR[lado], emissive: COLOR[lado], emissiveIntensity: 0.35, roughness: 0.4 }))
  g.position.set(lado === 'left' ? -0.28 : 0.28, 1.05, 0.28)
  g.userData.lado = lado
  escena.add(g)
  return g
}
const marcadores = { left: crearMarcador('left'), right: crearMarcador('right') }

const fabricaManos = new XRHandModelFactory()
const manosXR = {}
const mandosXR = {}
LADOS.forEach((lado, i) => {
  const mano = render.xr.getHand(i)
  mano.add(fabricaManos.createHandModel(mano, 'mesh'))
  escena.add(mano)
  manosXR[lado] = mano
  const mando = render.xr.getController(i)
  const linea = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -0.08)]),
    new THREE.LineBasicMaterial({ color: COLOR[lado] }))
  mando.add(linea)
  escena.add(mando)
  mandosXR[lado] = mando
})

/** Devuelve posicion, apertura de pinza y validez de una mano en el marco de la escena. */
function leerMano (lado) {
  const mano = manosXR[lado]
  const art = mano && mano.joints
  if (art && art['wrist'] && art['wrist'].visible) {
    const p = art['wrist'].position
    let pinza = 1
    const pulgar = art['thumb-tip']; const indice = art['index-finger-tip']
    if (pulgar && indice) pinza = Math.min(1, pulgar.position.distanceTo(indice.position) / 0.07)
    return { p, pinza, fuente: 'mano' }
  }
  const mando = mandosXR[lado]
  if (mando && mando.visible && mando.position.lengthSq() > 0) {
    return { p: mando.position, pinza: 1, fuente: 'mando' }
  }
  return null
}

// ---------------------------------------------------------------- arrastre en escritorio
const rayo = new THREE.Raycaster()
const puntero = new THREE.Vector2()
const plano = new THREE.Plane()
const golpe = new THREE.Vector3()
let arrastrando = null

function aPuntero (ev) {
  puntero.x = (ev.clientX / innerWidth) * 2 - 1
  puntero.y = -(ev.clientY / innerHeight) * 2 + 1
}

render.domElement.addEventListener('pointerdown', (ev) => {
  if (render.xr.isPresenting) return
  aPuntero(ev)
  rayo.setFromCamera(puntero, camara)
  const toque = rayo.intersectObjects(Object.values(marcadores), false)[0]
  if (!toque) return
  arrastrando = toque.object
  orbita.enabled = false
  plano.setFromNormalAndCoplanarPoint(
    camara.getWorldDirection(new THREE.Vector3()).negate(), arrastrando.position)
})

render.domElement.addEventListener('pointermove', (ev) => {
  if (!arrastrando) return
  aPuntero(ev)
  rayo.setFromCamera(puntero, camara)
  if (rayo.ray.intersectPlane(plano, golpe)) arrastrando.position.copy(golpe)
})

addEventListener('pointerup', () => { arrastrando = null; orbita.enabled = true })

// Teclas: C calibrar, R reposo, G grabar o parar.
addEventListener('keydown', (ev) => {
  const t = (ev.target && ev.target.tagName) || ''
  if (t === 'INPUT' || t === 'TEXTAREA') return
  const k = ev.key.toLowerCase()
  if (k === 'c') puente.cmd('calibrar')
  if (k === 'r') puente.cmd('reset')
  if (k === 'g') alternarGrabacion()
})

// ---------------------------------------------------------------- puente
const puente = new Puente()
const estado = { tramas: 0, grabando: false, episodio: null, aviso: '', diag: null }

$('url').value = `ws://${location.hostname || 'localhost'}:8765`

$('conectar').onclick = () => {
  if (puente.conectado) { puente.cerrar(); return }
  estado.aviso = 'conectando'
  pintarPanel()
  puente.conectar($('url').value.trim())
}
$('calibrar').onclick = () => puente.cmd('calibrar')
$('reset').onclick = () => puente.cmd('reset')
$('grabar').onclick = () => alternarGrabacion()

function alternarGrabacion () {
  if (estado.grabando) puente.cmd('parar')
  else puente.cmd('grabar', { tarea: $('tarea').value.trim() || 'sin_nombre' })
}

puente.addEventListener('hola', async (ev) => {
  const m = ev.detail
  estado.aviso = `robot ${m.robot}`
  pintarPanel()
  try {
    await vista.cargar(m.glb, m.bodies)
    estado.diag = vista.diagnostico()
    if (estado.diag.sinMapear) console.warn('mallas sin body', vista.sinMapear.slice(0, 10))
  } catch (e) {
    estado.aviso = `no cargo el modelo: ${e.message}`
  }
  pintarPanel()
})

puente.addEventListener('estado', (ev) => {
  const m = ev.detail
  vista.aplicar(m.p, m.q)
  estado.tramas = puente.tramas
  estado.grabando = m.grabando
  estado.n = m.n
})

puente.addEventListener('aviso', (ev) => {
  const m = ev.detail
  if (m.type === 'grabando') { estado.grabando = true; estado.episodio = m.episodio; estado.aviso = `grabando ${m.episodio}` }
  else if (m.type === 'grabado') { estado.grabando = false; estado.aviso = `guardado ${m.meta.tramas} tramas` }
  else if (m.texto) estado.aviso = m.texto
  pintarPanel()
})

puente.addEventListener('abierto', () => { estado.aviso = 'conectado'; pintarPanel() })
puente.addEventListener('cerrado', () => { estado.aviso = 'desconectado'; pintarPanel() })
puente.addEventListener('error', () => { estado.aviso = 'error de conexion'; pintarPanel() })

// ---------------------------------------------------------------- panel
function pintarPanel () {
  $('luz').classList.toggle('on', puente.conectado)
  $('conectar').textContent = puente.conectado ? 'Desconectar' : 'Conectar'
  $('grabar').textContent = estado.grabando ? '■ Parar' : '● Grabar'
  const d = estado.diag
  $('estado').innerHTML =
    `<span class="punto${puente.conectado ? ' on' : ''}" id="luz"></span>${estado.aviso || 'sin conectar'}` +
    `\ntramas ${estado.tramas}${estado.grabando ? ` · grabadas ${estado.n || 0}` : ''}` +
    (d ? `\npiezas ${d.mapeados}/${d.bodies} · mallas ${d.mallas}${d.sinMapear ? ` · sueltas ${d.sinMapear}` : ''}` : '')
}
pintarPanel()

// ---------------------------------------------------------------- botones XR
const zonaXR = $('xr')

/** Los botones de three traen posicion propia; aqui van dentro del panel. */
function colocar (btn) {
  Object.assign(btn.style, {
    position: 'static', width: 'auto', padding: '9px 14px', font: '600 13px system-ui',
    border: '1px solid #27304f', borderRadius: '10px', background: '#1b2340',
    color: '#e8ecfb', opacity: '1', cursor: 'pointer', letterSpacing: '.2px',
  })
  zonaXR.appendChild(btn)
}

colocar(VRButton.createButton(render, { optionalFeatures: ['hand-tracking', 'local-floor'] }))
if (navigator.xr) {
  navigator.xr.isSessionSupported('immersive-ar').then((ok) => {
    if (ok) colocar(ARButton.createButton(render, { optionalFeatures: ['hand-tracking', 'local-floor'] }))
  }).catch(() => {})
}

render.xr.addEventListener('sessionstart', () => {
  const modo = render.xr.getSession().environmentBlendMode
  const ar = modo && modo !== 'opaque'
  decorado.visible = !ar
  Object.values(marcadores).forEach((m) => { m.visible = false })
  // En AR el robot se coloca un poco al frente para verlo entero.
  mundo.position.set(0, 0, ar ? -0.9 : 0)
})

render.xr.addEventListener('sessionend', () => {
  decorado.visible = true
  Object.values(marcadores).forEach((m) => { m.visible = true })
  mundo.position.set(0, 0, 0)
})

// ---------------------------------------------------------------- bucle
const cabeza = new THREE.Vector3()

function paquete () {
  const datos = {}
  if (render.xr.isPresenting) {
    for (const lado of LADOS) {
      const m = leerMano(lado)
      if (m) datos[lado] = { p: tresAmj(m.p), pinza: m.pinza, fuente: m.fuente }
    }
    render.xr.getCamera().getWorldPosition(cabeza)
    datos.head = { p: tresAmj(cabeza) }
  } else {
    for (const lado of LADOS) {
      datos[lado] = { p: tresAmj(marcadores[lado].position), pinza: 1, fuente: 'raton' }
    }
    datos.head = { p: tresAmj(camara.position) }
  }
  return datos
}

render.setAnimationLoop(() => {
  if (!render.xr.isPresenting) orbita.update()
  if (puente.conectado) puente.enviarManos(paquete(), 30)
  render.render(escena, camara)
})

addEventListener('resize', () => {
  camara.aspect = innerWidth / innerHeight
  camara.updateProjectionMatrix()
  render.setSize(innerWidth, innerHeight)
})

// Para depurar desde la consola del navegador.
window.xr = { escena, camara, render, vista, puente, marcadores, estado }
