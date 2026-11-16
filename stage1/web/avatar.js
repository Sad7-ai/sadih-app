// صادِح avatar player. Plays the model's motion (CONTRACT-MOTION.md, "soke133" at 24 fps) on the SMPL-X body
// made by tools/smplx_to_glb.py. Its bones ARE the SMPL-X joints with identity rest rotations, so each
// axis-angle triple is set straight onto its bone: no retargeting, no per-bone corrections.
//
//   const av = new SadihAvatar(hostElement); await av.load("/avatar.glb?code=…"); av.enqueue(motionMessage);
//
// Clips play in unit order. Between clips the pose blends for BLEND_S, and while clips are waiting the player
// runs up to MAX_RATE faster, so it catches up instead of falling further behind the speaker.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const FPS = 24, DIM = 133;
const BLEND_S = 0.25;                 // clip-to-clip blend
const MAX_RATE = 1.25;                // fastest playback while clips are queued
// feature offset -> SMPL-X joint, in the 133 order fixed by SOKE (CONTRACT-MOTION.md)
const MAP = [];
for (let k = 0; k < 10; k++) MAP.push([3 * k, 12 + k]);           // neck .. right wrist (12..21)
for (let k = 0; k < 15; k++) MAP.push([30 + 3 * k, 25 + k]);      // left hand (25..39)
for (let k = 0; k < 15; k++) MAP.push([75 + 3 * k, 40 + k]);      // right hand (40..54)
MAP.push([120, 22]);                                              // jaw
const EXPR = 123, N_EXPR = 10;
// Shown only before the first clip arrives: arms lowered from SMPL-X's zero (T) pose. Cosmetic, not model output.
// After any clip, the player holds that clip's last frame, which is real signing data.
const IDLE = new Float32Array(DIM);
IDLE[3 * 4 + 2] = -1.2;               // left shoulder, about z: arm down
IDLE[3 * 5 + 2] = 1.2;                // right shoulder

const HALF = (() => {                 // float16 -> float32, all 65 536 values once
  const t = new Float32Array(65536);
  for (let h = 0; h < 65536; h++) {
    const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 31, f = h & 1023;
    t[h] = e === 0 ? s * 2 ** -14 * (f / 1024) : e === 31 ? (f ? NaN : s * Infinity) : s * 2 ** (e - 15) * (1 + f / 1024);
  }
  return t;
})();

export function decodeMotion(b64, frames) {
  const bin = atob(b64);
  if (bin.length !== frames * DIM * 2) throw new Error(`motion is ${bin.length} bytes, expected ${frames * DIM * 2}`);
  const out = new Float32Array(frames * DIM);
  for (let i = 0; i < out.length; i++) out[i] = HALF[bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)];
  return out;
}

const _v = new THREE.Vector3();
function aaToQuat(x, y, z, q) {        // axis-angle -> quaternion (three.js order x, y, z, w)
  const th = Math.hypot(x, y, z);
  if (th < 1e-9) return q.set(0, 0, 0, 1);
  const s = Math.sin(th / 2) / th;
  return q.set(x * s, y * s, z * s, Math.cos(th / 2));
}

// one clip, turned into per-frame quaternions once, so playback only interpolates
function prepare(feat, frames) {
  const quats = new Float32Array(frames * MAP.length * 4), expr = new Float32Array(frames * N_EXPR);
  const q = new THREE.Quaternion();
  for (let f = 0; f < frames; f++) {
    const row = f * DIM;
    MAP.forEach(([off], j) => {
      aaToQuat(feat[row + off], feat[row + off + 1], feat[row + off + 2], q);
      quats.set([q.x, q.y, q.z, q.w], (f * MAP.length + j) * 4);
    });
    for (let k = 0; k < N_EXPR; k++) expr[f * N_EXPR + k] = feat[row + EXPR + k];
  }
  return { quats, expr, frames };
}

export class SadihAvatar {
  constructor(host) {
    this.host = host;
    this.queue = [];
    this.clip = null;                 // { quats, expr, frames, t, unit_id, model }
    this.from = null;                 // pose captured at a clip switch, blended out over BLEND_S
    this.blend = 1;
    this.s = { loaded: false, error: "", received: 0, played: 0, frames: 0, rate: 1, lag_s: 0, model: "", unit: null };
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.canvas = this.renderer.domElement;
    this.canvas.className = "av-canvas";
    host.prepend(this.canvas);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(26, 1, 0.05, 20);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x1a1a1a, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(0.6, 1.2, 2.2);
    this.scene.add(key);
    this.clock = new THREE.Clock();
    new ResizeObserver(() => this._resize()).observe(host);
  }

  get stats() { return { ...this.s, queued: this.queue.length, playing: !!this.clip }; }

  async load(url) {
    try {
      const gltf = await new GLTFLoader().loadAsync(url);
      this.root = gltf.scene;
      this.bones = [];
      this.root.traverse(o => {
        if (o.isBone) { const m = /^(\d\d)_/.exec(o.name); if (m) this.bones[+m[1]] = o; }
        if (o.isSkinnedMesh) {
          this.mesh = o;
          o.frustumCulled = false;   // the bind-pose bounds do not follow the pose
          o.material = new THREE.MeshStandardMaterial({ color: 0xcdcdcd, roughness: 0.82, metalness: 0 });
        }
      });
      if (!this.mesh || MAP.some(([, j]) => !this.bones[j])) throw new Error("this file is not the SMPL-X avatar (tools/smplx_to_glb.py)");
      this.expr = Array.from({ length: N_EXPR }, (_, k) => this.mesh.morphTargetDictionary?.["expr" + k]);
      this.scene.add(this.root);
      this.idle = prepare(IDLE, 1);
      this._apply(this.idle, 0, 0, 1);
      this._frame();
      this.s.loaded = true;
      this._resize();
      this.renderer.setAnimationLoop(() => this._tick());
    } catch (e) {
      this.s.error = String(e.message || e);
      throw e;
    }
  }

  // aim at the signing space: waist to just above the head, wide enough for the hands at full reach
  _frame() {
    this.root.updateMatrixWorld(true);
    const head = this.bones[15].getWorldPosition(new THREE.Vector3());
    const pelvis = this.bones[0].getWorldPosition(new THREE.Vector3());
    this.lo = pelvis.y - 0.12; this.hi = head.y + 0.2; this.cy = (this.lo + this.hi) / 2;
  }

  _resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    const t = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const dh = (this.hi - this.lo) / 2 / t, dw = 1.15 / 2 / (t * this.camera.aspect);
    const d = Math.max(dh || 2, dw || 2);
    this.camera.position.set(0, this.cy || 0, d);
    this.camera.lookAt(0, this.cy || 0, 0);
    this.camera.updateProjectionMatrix();
  }

  attach(host) {                       // move the one canvas between the full app and the floating window
    if (host === this.host) return;
    this.host = host;
    host.prepend(this.canvas);
    new ResizeObserver(() => this._resize()).observe(host);
    this._resize();
  }

  enqueue(m) {
    const feat = decodeMotion(m.motion, m.frames);
    this.queue.push({ ...prepare(feat, m.frames), t: 0, unit_id: m.unit_id, model: m.model });
    this.s.received++;
  }

  clear() { this.queue = []; this.clip = null; }

  _snapshot() {
    const quats = new Float32Array(MAP.length * 4), expr = new Float32Array(N_EXPR);
    MAP.forEach(([, j], k) => { const q = this.bones[j].quaternion; quats.set([q.x, q.y, q.z, q.w], k * 4); });
    if (this.mesh.morphTargetInfluences) this.expr.forEach((i, k) => { if (i != null) expr[k] = this.mesh.morphTargetInfluences[i]; });
    return { quats, expr, frames: 1 };
  }

  // pose = clip at frame f + a (0..1), then blended from `this.from` with weight w (1 = all clip)
  _apply(c, f, a, w) {
    const f1 = Math.min(f + 1, c.frames - 1);
    const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), qf = new THREE.Quaternion();
    MAP.forEach(([, j], k) => {
      const i0 = (f * MAP.length + k) * 4, i1 = (f1 * MAP.length + k) * 4;
      qa.fromArray(c.quats, i0); qb.fromArray(c.quats, i1);
      qa.slerp(qb, a);
      if (w < 1 && this.from) { qf.fromArray(this.from.quats, k * 4); qa.copy(qf.slerp(qa, w)); }
      this.bones[j].quaternion.copy(qa);
    });
    const inf = this.mesh.morphTargetInfluences;
    if (inf) this.expr.forEach((i, k) => {
      if (i == null) return;
      let e = c.expr[f * N_EXPR + k] * (1 - a) + c.expr[f1 * N_EXPR + k] * a;
      if (w < 1 && this.from) e = this.from.expr[k] * (1 - w) + e * w;
      inf[i] = e;
    });
  }

  _tick() {
    const dt = Math.min(this.clock.getDelta(), 0.1);
    if (!this.clip && this.queue.length) {
      this.from = this._snapshot(); this.blend = 0;
      this.clip = this.queue.shift();
      this.s.model = this.clip.model; this.s.unit = this.clip.unit_id;
    }
    const c = this.clip;
    if (c) {
      this.s.rate = this.queue.length ? MAX_RATE : 1;
      c.t += dt * FPS * this.s.rate;
      this.blend = Math.min(1, this.blend + dt / BLEND_S);
      const w = this.blend * this.blend * (3 - 2 * this.blend);
      if (c.t >= c.frames - 1) {
        this._apply(c, c.frames - 1, 0, 1);          // hold the last real frame until the next clip
        this.clip = null; this.s.played++;
      } else {
        this._apply(c, Math.floor(c.t), c.t - Math.floor(c.t), w);
      }
      this.s.frames++;
    }
    const left = (c ? Math.max(0, c.frames - c.t) : 0) + this.queue.reduce((n, q) => n + q.frames, 0);
    this.s.lag_s = Math.round((left / FPS) * 10) / 10;
    this.renderer.render(this.scene, this.camera);
  }

  // for tests: pose one 133-number frame right now and read a joint's world position back
  poseForTest(row) { this._apply(prepare(Float32Array.from(row), 1), 0, 0, 1); this.root.updateMatrixWorld(true); }
  jointWorld(j) { return this.bones[j].getWorldPosition(_v).toArray(); }
}
