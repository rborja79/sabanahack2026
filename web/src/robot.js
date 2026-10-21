/** Carga el GLB del robot y aplica, trama a trama, la pose de cada pieza. */
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

// MuJoCo trabaja con Z arriba; WebXR con Y arriba.
export const mjAtres = (p) => new THREE.Vector3(p[0], p[2], -p[1])
export const tresAmj = (v) => [v.x, -v.z, v.y]

/** Saca el nombre del body del nombre del nodo exportado: "torso_link__12". */
function nombreBody (nodo) {
  for (let n = nodo; n; n = n.parent) {
    const txt = n.name || ''
    if (txt.includes('__')) return txt.split('__')[0]
  }
  return (nodo.name || '').split('__')[0]
}

export class RobotVista {
  constructor (escena) {
    this.raiz = new THREE.Group()
    this.marco = new THREE.Group()      // dentro de este grupo rige el marco de MuJoCo
    this.marco.rotation.x = -Math.PI / 2
    this.raiz.add(this.marco)
    escena.add(this.raiz)
    this.piezas = new Map()
    this.bodies = []
    this.sinMapear = []
    this.listo = false
  }

  async cargar (url, bodies) {
    this.bodies = bodies
    const gltf = await new GLTFLoader().loadAsync(url)
    const mallas = []
    gltf.scene.updateMatrixWorld(true)
    gltf.scene.traverse((n) => { if (n.isMesh) mallas.push(n) })
    const validos = new Set(bodies)
    for (const n of mallas) {
      const base = n.matrixWorld.clone()
      this.marco.add(n)
      n.matrixAutoUpdate = false
      n.frustumCulled = false
      n.userData.base = base
      n.matrix.copy(base)
      if (n.material) { n.material.metalness = 0.25; n.material.roughness = 0.6 }
      const body = nombreBody(n)
      if (!validos.has(body)) { this.sinMapear.push(n.name || '?'); continue }
      if (!this.piezas.has(body)) this.piezas.set(body, [])
      this.piezas.get(body).push(n)
    }
    this.listo = true
    return this
  }

  /** p y q vienen planos: 3 y 4 valores por body, en el orden de `bodies`. */
  aplicar (p, q) {
    if (!this.listo) return
    const pos = new THREE.Vector3(); const rot = new THREE.Quaternion()
    const esc = new THREE.Vector3(1, 1, 1); const M = new THREE.Matrix4()
    for (let i = 0; i < this.bodies.length; i++) {
      const nodos = this.piezas.get(this.bodies[i])
      if (!nodos) continue
      pos.set(p[i * 3], p[i * 3 + 1], p[i * 3 + 2])
      rot.set(q[i * 4 + 1], q[i * 4 + 2], q[i * 4 + 3], q[i * 4]) // wxyz -> xyzw
      M.compose(pos, rot, esc)
      for (const n of nodos) n.matrix.copy(M).multiply(n.userData.base)
    }
  }

  diagnostico () {
    return {
      bodies: this.bodies.length,
      mapeados: this.piezas.size,
      mallas: [...this.piezas.values()].reduce((a, v) => a + v.length, 0),
      sinMapear: this.sinMapear.length,
    }
  }
}
