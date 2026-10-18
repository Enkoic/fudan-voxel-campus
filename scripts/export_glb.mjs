#!/usr/bin/env node
/**
 * Export the three campus models as portable binary glTF files.
 *
 *   models/fudan-handan.glb
 *   models/fudan-jiangwan.glb
 *   models/fudan-fenglin.glb
 *   models/fudan-three-campuses.glb
 *
 * The exporter uses a real canvas (@napi-rs/canvas) for textures and labels,
 * and bakes the instanced trees into ordinary meshes for maximum compatibility.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { GLTFExporter } from './../node_modules/three/examples/jsm/exporters/GLTFExporter.js';
import { createCanvas, GlobalFonts, ImageData as NapiImageData } from '@napi-rs/canvas';

import { createTextureLibrary } from '../src/textures.js';
import { createMaterials, CampusModel } from '../src/campusScene.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'models');
fs.mkdirSync(OUT, { recursive: true });

/* ------------------------------------------------------------------ environment */
GlobalFonts.registerFromPath('/System/Library/Fonts/STHeiti Medium.ttc', 'FudanSans');
GlobalFonts.registerFromPath('/System/Library/Fonts/Hiragino Sans GB.ttc', 'FudanSansGB');
const CanvasClass = createCanvas(1, 1).constructor;
// @napi-rs/canvas exposes a `data` function on its prototype. Three's
// GLTFExporter mistakes that for a DataTexture; masking it forces the normal
// HTMLCanvasElement copy path so images are not exported as transparent black.
CanvasClass.prototype.data = undefined;
// Serialise PNG encoding; concurrent napi-canvas encodes can crash on large scenes.
const blobQueue = [];
let blobBusy = false;
function pumpBlobs() {
  if (blobBusy) return;
  const task = blobQueue.shift();
  if (!task) return;
  blobBusy = true;
  setTimeout(() => {
    try { task(); } catch (err) { console.error('texture encode failed', err); }
    blobBusy = false;
    pumpBlobs();
  }, 0);
}
CanvasClass.prototype.toBlob = function (cb, type = 'image/png') {
  const canvas = this;
  blobQueue.push(() => {
    const buf = canvas.toBuffer(type);
    cb(new Blob([buf], { type }));
  });
  pumpBlobs();
};
globalThis.HTMLCanvasElement = CanvasClass;
globalThis.ImageData = NapiImageData;
globalThis.document = {
  createElement(tag) {
    if (tag === 'canvas') return createCanvas(1, 1);
    return {};
  },
  createElementNS() { return createCanvas(1, 1); },
};
globalThis.FileReader = class FileReader {
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then((buf) => {
      this.result = buf;
      this.onloadend?.();
    }).catch((err) => this.onerror?.(err));
  }
};

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'campuses.json'), 'utf8'));
const textures = createTextureLibrary(createCanvas);
const materials = createMaterials(textures, null);

/* ------------------------------------------------------------------ helpers */
function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function textTexture(title, sub, { width = 1024, height = 256, accent = '#b08a4a', compact = false } = {}) {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  if (compact) {
    ctx.fillStyle = 'rgba(20,17,14,0.84)';
    commonRoundRect(ctx, 4, 8, width - 8, height - 16, 10);
    ctx.fill();
    ctx.strokeStyle = 'rgba(216,189,133,0.35)';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = accent;
    ctx.fillRect(4, 8, 7, height - 16);
    ctx.fillStyle = '#f5efe3';
    ctx.font = `${Math.round(height * 0.43)}px FudanSans, FudanSansGB, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(title, 28, sub ? height * 0.42 : height * 0.52);
    if (sub) {
      ctx.fillStyle = 'rgba(245,239,227,0.60)';
      ctx.font = `${Math.round(height * 0.19)}px FudanSans, sans-serif`;
      ctx.fillText(sub, 30, height * 0.74);
    }
  } else {
    ctx.fillStyle = '#17130f';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = accent;
    ctx.fillRect(0, 0, 12, height);
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.fillRect(12, height - 4, width - 12, 4);
    ctx.fillStyle = '#f4ecdd';
    ctx.font = `600 ${Math.round(height * 0.36)}px FudanSans, FudanSansGB, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(title, 48, height * 0.39);
    ctx.fillStyle = 'rgba(216,189,133,0.88)';
    ctx.font = `${Math.round(height * 0.13)}px FudanSans, FudanSansGB, sans-serif`;
    ctx.fillText(sub, 50, height * 0.72);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  tex.flipY = false;
  tex.name = `label-${title}`;
  return tex;
}

function commonRoundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function flipPlaneUV(geom) {
  const uv = geom.attributes.uv;
  for (let i = 0; i < uv.count; i++) uv.setY(i, 1 - uv.getY(i));
  uv.needsUpdate = true;
  return geom;
}

function labelMesh(text, sub, { y, x, z, height = 8, compact = true, accent = '#b08a4a' }) {
  const tex = textTexture(text, sub, { compact, accent });
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    side: THREE.DoubleSide,
    depthWrite: false,
    toneMapped: false,
  });
  const aspect = tex.image.width / tex.image.height;
  const geom = flipPlaneUV(new THREE.PlaneGeometry(height * aspect, height));
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.set(x, y, z);
  mesh.renderOrder = 20;
  mesh.name = `label-${text}`;
  return mesh;
}

function plaque(group, data) {
  const maxZ = Math.max(...data.base.map((p) => p[1]));
  const width = 270;
  const height = 72;
  const z = maxZ + 36;
  const back = new THREE.Mesh(
    new THREE.BoxGeometry(width + 12, height + 12, 5),
    new THREE.MeshStandardMaterial({ color: '#1a1612', roughness: 0.82, metalness: 0.05 })
  );
  back.position.set(0, height / 2 + 26, z);
  back.name = 'campus-plaque-back';
  group.add(back);

  const title = `${data.name}`;
  const sub = `${data.en.toUpperCase()}  ·  ${data.areaLabel}`;
  const tex = textTexture(title, sub, { width: 1280, height: 340 });
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide, toneMapped: false });
  const plane = new THREE.Mesh(flipPlaneUV(new THREE.PlaneGeometry(width, height)), mat);
  plane.position.set(0, height / 2 + 26, z);
  plane.rotation.y = THREE.MathUtils.degToRad(26);
  back.rotation.y = plane.rotation.y;
  plane.translateZ(3.1);
  plane.name = 'campus-plaque';
  group.add(plane);
}

function addBuildingLabels(group, data) {
  const labels = data.labels
    .filter((l) => l.kind === 'building' || l.kind === 'area')
    .sort((a, b) => (a.priority || 99) - (b.priority || 99))
    .slice(0, 8);
  for (const l of labels) {
    const height = l.kind === 'area' ? 20 : 22;
    const y = (l.y || 4) + (l.kind === 'area' ? 8 : 10);
    const mesh = labelMesh(l.text, l.sub || '', {
      x: l.x,
      y,
      z: l.z,
      height,
      compact: true,
      accent: l.kind === 'area' ? '#9bb8a8' : '#c7a15d',
    });
    mesh.userData.labelKind = l.kind;
    group.add(mesh);
  }
}

/* ------------------------------------------------------------------ trees */
function colorize(geom, color) {
  const count = geom.attributes.position.count;
  const arr = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    arr[i * 3] = color.r;
    arr[i * 3 + 1] = color.g;
    arr[i * 3 + 2] = color.b;
  }
  geom.setAttribute('color', new THREE.BufferAttribute(arr, 3));
  return geom;
}

function lowPolyTree(variant) {
  const parts = [];
  const trunk = new THREE.CylinderGeometry(0.26, 0.46, 3.8, 4, 1);
  trunk.translate(0, 1.9, 0);
  colorize(trunk, new THREE.Color('#4b3929'));
  parts.push(trunk);
  const blobs = variant === 0
    ? [[0, 5.8, 0, 3.0], [1.6, 4.8, 0.4, 1.9], [-1.4, 5.1, -0.4, 1.8]]
    : variant === 1
      ? [[0, 6.1, 0, 3.2], [0.5, 4.4, 1.3, 1.9], [-1.2, 5.3, -1.0, 1.9]]
      : [[0, 5.4, 0, 2.8], [1.3, 6.2, -0.3, 1.9], [-1.5, 4.7, 0.8, 1.8]];
  for (let i = 0; i < blobs.length; i++) {
    const [x, y, z, r] = blobs[i];
    const g = new THREE.IcosahedronGeometry(r, 0);
    g.translate(x, y, z);
    colorize(g, new THREE.Color().setHSL(0.235 + i * 0.01, 0.32, 0.29 - i * 0.012));
    parts.push(g);
  }
  const merged = mergeGeometries(parts.map((g) => (g.index ? g.toNonIndexed() : g)), false);
  merged.deleteAttribute('uv');
  return merged;
}

function bakeTrees(group, data, material, step = 1) {
  const inst = [];
  group.traverse((n) => { if (n.isInstancedMesh) inst.push(n); });
  for (const mesh of inst) {
    mesh.parent.remove(mesh);
  }
  const cols = [lowPolyTree(0), lowPolyTree(1), lowPolyTree(2)];
  const geoms = [];
  let i = 0;
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const pos = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (const t of data.trees) {
    if (i++ % step !== 0) continue;
    const [x, z, s, v] = t;
    q.setFromAxisAngle(up, rnd() * Math.PI * 2);
    pos.set(x, 0.08, z);
    scale.set(s, s * (0.92 + rnd() * 0.18), s);
    m.compose(pos, q, scale);
    const g = cols[v % 3].clone();
    g.deleteAttribute('uv');
    g.applyMatrix4(m);
    const tint = 0.84 + rnd() * 0.28;
    const arr = g.attributes.color.array;
    for (let k = 0; k < arr.length; k++) arr[k] *= tint;
    g.attributes.color.needsUpdate = true;
    geoms.push(g);
  }
  if (geoms.length) {
    const merged = mergeGeometries(geoms, false);
    for (const g of geoms) g.dispose();
    if (merged) {
      const mesh = new THREE.Mesh(merged, material);
      mesh.name = 'trees-baked';
      mesh.castShadow = false;
      mesh.receiveShadow = false;
      group.add(mesh);
      return geoms.length;
    }
  }
  return 0;
}

/* ------------------------------------------------------------------ scene lights */
function addLights(scene) {
  const key = new THREE.DirectionalLight('#fff1d6', 2.2);
  key.position.set(-2400, 4200, 2600);
  key.name = 'Key-Light';
  key.target.position.set(0, 0, -1);
  key.add(key.target);
  key.lookAt(0, 0, 0);
  scene.add(key);

  const fill = new THREE.DirectionalLight('#b8d0e8', 0.8);
  fill.position.set(2800, 2200, -1800);
  fill.name = 'Fill-Light';
  fill.target.position.set(0, 0, -1);
  fill.add(fill.target);
  fill.lookAt(0, 0, 0);
  scene.add(fill);
}

async function exportScene(scene, file) {
  const exporter = new GLTFExporter();
  const buffer = await exporter.parseAsync(scene, {
    binary: true,
    onlyVisible: true,
    trs: false,
    maxTextureSize: 2048,
  });
  fs.writeFileSync(file, Buffer.from(buffer));
  const kb = fs.statSync(file).size / 1024 / 1024;
  console.log(`  ✓ ${path.basename(file)} (${kb.toFixed(1)} MB)`);
}

/* ------------------------------------------------------------------ build */
const groups = new Map();
for (const c of data.campuses) {
  console.log(`Building ${c.name}...`);
  const model = new CampusModel(c, materials, { shadows: false, forExport: true });
  const group = model.group;
  group.name = `Fudan-${c.id}`;
  group.userData = {
    campus: c.id,
    name: c.name,
    en: c.en,
    address: c.address,
    source: 'OpenStreetMap ODbL; heights curated/estimated',
  };
  plaque(group, c);
  addBuildingLabels(group, c);
  const baked = bakeTrees(group, c, materials.tree, 1);
  console.log(`  ${c.stats.buildings} buildings, ${baked} baked trees, ${c.labels.length} labels`);
  groups.set(c.id, group);
}

const models = [
  ['handan', 'fudan-handan.glb'],
  ['jiangwan', 'fudan-jiangwan.glb'],
  ['fenglin', 'fudan-fenglin.glb'],
];

for (const [id, filename] of models) {
  const scene = new THREE.Scene();
  scene.name = `Fudan-${id}`;
  addLights(scene);
  const group = groups.get(id);
  scene.add(group);
  await exportScene(scene, path.join(OUT, filename));
  scene.remove(group);
}

// Keep the combined model clean: campus plaques only, no per-building labels.
for (const group of groups.values()) {
  const toRemove = [];
  group.traverse((o) => {
    if (o.isMesh && o.name.startsWith('label-')) toRemove.push(o);
  });
  for (const o of toRemove) o.parent.remove(o);
}

// combined model
const combined = new THREE.Scene();
combined.name = 'Fudan-University-Three-Campuses';
addLights(combined);

const platform = new THREE.Mesh(
  new THREE.BoxGeometry(4800, 42, 3900),
  new THREE.MeshStandardMaterial({ color: '#d9d1c2', roughness: 0.96, metalness: 0.0 })
);
platform.position.set(0, -64, 70);
platform.name = 'model-platform';
combined.add(platform);

const positions = {
  handan: [-1050, 0, -470],
  jiangwan: [1050, 0, -470],
  fenglin: [0, 0, 870],
};
for (const [id, group] of groups) {
  const [x, y, z] = positions[id];
  group.position.set(x, y, z);
  combined.add(group);
}

combined.userData = {
  title: '复旦大学 · 一校三区',
  subtitle: '邯郸 · 江湾 · 枫林',
  note: '建筑轮廓与场地数据 © OpenStreetMap contributors (ODbL 1.0)。高度、立面与景观为公开资料整理及示意性推定，非测绘成果。',
  generated: '2026-10-18',
};
console.log('Building combined model...');
await exportScene(combined, path.join(OUT, 'fudan-three-campuses.glb'));

console.log('Done.');
