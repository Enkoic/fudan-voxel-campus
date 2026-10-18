#!/usr/bin/env node
/**
 * Export the voxel campus scenes as portable GLB files.
 * Merged cubes (no instancing extension) keep the files readable in Blender,
 * SketchUp, Rhino and other glTF importers.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { GLTFExporter } from './../node_modules/three/examples/jsm/exporters/GLTFExporter.js';
import { createCanvas, GlobalFonts, ImageData as NapiImageData } from '@napi-rs/canvas';
import { createVoxelCampus } from '../src/voxel/voxelScene.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'models');
fs.mkdirSync(OUT, { recursive: true });

GlobalFonts.registerFromPath('/System/Library/Fonts/STHeiti Medium.ttc', 'FudanSans');
GlobalFonts.registerFromPath('/System/Library/Fonts/Hiragino Sans GB.ttc', 'FudanSansGB');
const CanvasClass = createCanvas(1, 1).constructor;
CanvasClass.prototype.data = undefined;
const blobQueue = [];
let blobBusy = false;
function pumpBlobs() {
  if (blobBusy) return;
  const task = blobQueue.shift();
  if (!task) return;
  blobBusy = true;
  setTimeout(() => {
    try { task(); } catch (e) { console.error('texture encode failed', e); }
    blobBusy = false;
    pumpBlobs();
  }, 0);
}
CanvasClass.prototype.toBlob = function (cb, type = 'image/png') {
  const canvas = this;
  blobQueue.push(() => cb(new Blob([canvas.toBuffer(type)], { type })));
  pumpBlobs();
};
globalThis.HTMLCanvasElement = CanvasClass;
globalThis.ImageData = NapiImageData;
globalThis.document = {
  createElement(tag) { return tag === 'canvas' ? createCanvas(1, 1) : {}; },
  createElementNS() { return createCanvas(1, 1); },
};
globalThis.FileReader = class FileReader {
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then((b) => { this.result = b; this.onloadend?.(); }).catch((e) => this.onerror?.(e));
  }
};

const data = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'campuses.json'), 'utf8'));
const CAMPUS_LABEL = { handan: '邯郸校区', jiangwan: '江湾校区', fenglin: '枫林校区' };
const CAMPUS_EN = { handan: 'HANDAN CAMPUS · 1922', jiangwan: 'JIANGWAN CAMPUS · 2005', fenglin: 'FENGLIN CAMPUS · 1937' };

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
function textTexture(title, sub, { width = 512, height = 128, plaque = false } = {}) {
  const canvas = createCanvas(width, height);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  if (plaque) {
    ctx.fillStyle = '#17130f';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#b08a4a';
    ctx.fillRect(0, 0, 10, height);
    ctx.fillStyle = '#f4ecdd';
    ctx.font = `600 ${Math.round(height * 0.38)}px FudanSans, FudanSansGB, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(title, 36, height * 0.39);
    ctx.fillStyle = 'rgba(216,189,133,0.85)';
    ctx.font = `${Math.round(height * 0.13)}px FudanSans, sans-serif`;
    ctx.fillText(sub, 38, height * 0.75);
  } else {
    ctx.fillStyle = 'rgba(22,18,14,0.92)';
    roundRect(ctx, 3, 6, width - 6, height - 12, 8);
    ctx.fill();
    ctx.fillStyle = '#b08a4a';
    ctx.fillRect(3, 6, 8, height - 12);
    ctx.fillStyle = '#f5efe3';
    ctx.font = `600 ${Math.round(height * 0.34)}px FudanSans, FudanSansGB, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(title, 23, sub ? height * 0.4 : height * 0.53);
    if (sub) {
      ctx.fillStyle = 'rgba(245,239,227,0.62)';
      ctx.font = `${Math.round(height * 0.16)}px FudanSans, sans-serif`;
      ctx.fillText(sub, 24, height * 0.73);
    }
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}
function flipV(plane) {
  const uv = plane.geometry.attributes.uv;
  for (let i = 0; i < uv.count; i++) uv.setY(i, 1 - uv.getY(i));
  uv.needsUpdate = true;
}
function makeLabel(text, sub, { width = 34, height = 8.6, plaque = false } = {}) {
  const w = plaque ? 280 : width;
  const h = plaque ? 74 : height;
  const tex = textTexture(text, sub, { width: plaque ? 1024 : 512, height: plaque ? 256 : 128, plaque });
  const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: !plaque, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  flipV(plane);
  plane.renderOrder = 4;
  plane.name = plaque ? 'voxel-plaque' : 'voxel-label';
  return plane;
}

function addPlaque(group, campus, box) {
  const plaque = makeLabel(CAMPUS_LABEL[campus.id], CAMPUS_EN[campus.id], { plaque: true });
  plaque.position.set(0, 64, box.maxZ + 42);
  group.add(plaque);
  // thin backing block, so the plate reads as an object even from the side
  const back = new THREE.Mesh(
    new THREE.BoxGeometry(284, 78, 3),
    new THREE.MeshStandardMaterial({ color: '#17130f', roughness: 0.9 })
  );
  back.position.set(0, 64, box.maxZ + 40.4);
  back.castShadow = true;
  group.add(back);
}
function addLabels(group, labels) {
  const picked = [...labels]
    .filter((l) => ['building', 'area', 'gate'].includes(l.kind))
    .sort((a, b) => (a.priority || 99) - (b.priority || 99))
    .slice(0, 8);
  for (const l of picked) {
    const plane = makeLabel(l.text, l.sub || '', { width: 34, height: 8.2 });
    plane.position.set(l.x, l.y, l.z + 2);
    group.add(plane);
  }
}

function bboxOf(group) {
  const b = new THREE.Box3().setFromObject(group);
  return b;
}

function buildCampus(campus, { labels = true, plaque = true } = {}) {
  const model = createVoxelCampus(campus, { mode: 'merged' });
  const group = model.group;
  group.name = `FUDAN-VOXEL-${campus.id.toUpperCase()}`;
  if (labels) addLabels(group, model.voxel.labels);
  return { group, model };
}

function exportScene(scene, filename) {
  return new Promise((resolve, reject) => {
    const exporter = new GLTFExporter();
    exporter.parse(scene, (result) => {
      const buf = Buffer.from(result);
      const out = path.join(OUT, filename);
      fs.writeFileSync(out, buf);
      console.log(`  ✓ ${filename} (${(buf.length / 1048576).toFixed(1)} MB)`);
      resolve();
    }, (err) => reject(err), { binary: true, onlyVisible: true });
  });
}

async function main() {
  const models = [];
  for (const campus of data.campuses) {
    console.log(`Building voxel ${campus.name}...`);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#e8dfcf');
    const { group, model } = buildCampus(campus);
    scene.add(group);
    const box = bboxOf(group);
    const center = box.getCenter(new THREE.Vector3());
    group.position.sub(center);
    group.position.y += box.getSize(new THREE.Vector3()).y / 2;
    // a light for viewers that do not add their own
    const key = new THREE.DirectionalLight('#fff2d8', 2.8);
    key.position.set(1200, 1600, 900);
    key.target.position.set(0, 0, -1);
    key.add(key.target);
    scene.add(key);
    const b = bboxOf(group);
    const maxDim = Math.max(b.max.x - b.min.x, b.max.z - b.min.z);
    // camera not exported; stored nowhere
    await exportScene(scene, `fudan-voxel-${campus.id}.glb`);
    models.push({ campus, group, model, bounds: b, maxDim });
  }

  console.log('Building combined voxel scene...');
  const combined = new THREE.Scene();
  combined.background = new THREE.Color('#e8dfcf');
  const layout = {
    handan: new THREE.Vector3(-1550, 0, -760),
    jiangwan: new THREE.Vector3(1550, 0, -760),
    fenglin: new THREE.Vector3(0, 0, 1460),
  };
  for (const { campus, group } of models) {
    // detach from its temporary scene and reuse
    group.position.set(0, 0, 0);
    group.position.copy(layout[campus.id]);
    combined.add(group);
  }
  const key = new THREE.DirectionalLight('#fff2d8', 2.8);
  key.position.set(2400, 3400, 1800);
  key.target.position.set(0, 0, -1);
  key.add(key.target);
  combined.add(key);
  await exportScene(combined, 'fudan-voxel-three-campuses.glb');
  console.log('Done.');
}
main().catch((e) => { console.error(e); process.exit(1); });
