// Дом объёмом: стены по контуру плана, фасад стороны — текстурой, крыша — плоская плита.
// Данные — /api/runs/<id>/house3d (render/house3d.py): метры плана, y вверх. В сцене three.js
// ось y — вверх, поэтому точка плана (x, y) стоит в (x, высота, −y).
// three.js грузится по адресу из config/viewer.toml только при открытии вкладки.

import { refusedFrom } from "/static/refusal.js";
import { Relief } from "/static/house3d_relief.js";

const ROOF_M = 0.15;  // толщина плиты крыши — только чтобы край был виден

let threeModule = null;

export class HouseStage {
  // look — [house3d] из config/viewer.toml (через /api/options).
  constructor(container, look) {
    this.container = container;
    this.look = look;
    this.view = { azimuth: -0.6, elevation: 0.45, distance: 1 };
  }

  async load(url) {
    const res = await fetch(url);
    if (!res.ok) throw await refusedFrom(res);
    const data = await res.json();
    threeModule ??= await import(this.look.three_url);
    this._scene(threeModule, data);
    await Promise.all(data.walls.map((w) => this._wall(threeModule, w)));
    this._bind();
    this.fit();
  }

  fit() {
    this.view = { ...this.view, distance: this.radius * 3.4 };
    this.render();
  }

  render() {
    const { azimuth: a, elevation: e, distance: d } = this.view;
    const c = this.center;
    this.camera.position.set(c.x + d * Math.cos(e) * Math.sin(a), c.y + d * Math.sin(e),
      c.z + d * Math.cos(e) * Math.cos(a));
    this.camera.lookAt(c);
    this.renderer.render(this.scene, this.camera);
  }

  _scene(THREE, data) {
    const { clientWidth: w, clientHeight: h } = this.container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(w, h);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.replaceChildren(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.look.background);
    this.camera = new THREE.PerspectiveCamera(35, w / h, 0.1, 1000);
    // Свет с двух сторон под разными углами: соседние стены дома разной яркости, угол читается.
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.6));
    for (const [x, y, z, k] of [[-1, 2, 1.5, 1.4], [1.5, 1, -1, 0.6]]) {
      const light = new THREE.DirectionalLight(0xffffff, k);
      light.position.set(x, y, z);
      this.scene.add(light);
    }
    const xs = data.corners.map(([x]) => x), zs = data.corners.map(([, y]) => -y);
    const mid = (v) => (Math.min(...v) + Math.max(...v)) / 2;
    this.center = new THREE.Vector3(mid(xs), data.eaves_m / 2, mid(zs));
    this.radius = Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs), data.eaves_m) / 2;
    this.relief = new Relief(THREE, this.look, data.trim);
    this.materials = new Map();  // цвет → материал: выступов на доме десятки, цветов — единицы
    this._roof(THREE, data);
    this._ground(THREE);
  }

  _roof(THREE, data) {
    if (data.roof.faces.length) return this._slopes(THREE, data.roof);
    const shape = new THREE.Shape(data.roof.flat.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ExtrudeGeometry(shape, { depth: ROOF_M, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);  // (x, y) плана → (x, −z); выдавливание — вверх
    const roof = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: this.look.roof }));
    roof.position.y = data.eaves_m;
    this.scene.add(roof, this._edges(THREE, geo, roof.position));
  }

  // Скаты и стены над карнизом (gf#320): выпуклые многоугольники (x, y плана, высота) → веер
  // треугольников; (x, y, h) плана → (x, h, −y) сцены, как у стен.
  _slopes(THREE, roof) {
    const parts = [[roof.faces, roof.color || this.look.roof], [roof.above, roof.wall || this.look.roof]];
    for (const [shapes, color] of parts) {
      for (const shape of shapes) {
        const points = shape.map(([x, y, h]) => new THREE.Vector3(x, h, -y));
        const fan = [];
        for (let i = 1; i + 1 < points.length; i++) fan.push(points[0], points[i], points[i + 1]);
        const geo = new THREE.BufferGeometry().setFromPoints(fan);
        geo.computeVertexNormals();
        const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color, side: THREE.DoubleSide }));
        this.scene.add(mesh, this._edges(THREE, geo));
      }
    }
  }

  _ground(THREE) {
    const ground = new THREE.Mesh(new THREE.CircleGeometry(this.radius * 4, 48),
      new THREE.MeshLambertMaterial({ color: this.look.ground }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(this.center.x, -0.01, this.center.z);
    this.scene.add(ground);
  }

  _edges(THREE, geo, position) {
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: this.look.edges }));
    if (position) lines.position.copy(position);
    return lines;
  }

  async _wall(THREE, w) {
    const texture = new THREE.CanvasTexture(await rasterize(w.svg, w.length_m, w.height_m, this.look.px_per_m));
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const geo = new THREE.PlaneGeometry(w.length_m, w.height_m);
    const wall = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: texture }));
    const [[lx, ly], [rx, ry]] = [w.left, w.right];
    wall.position.set((lx + rx) / 2, w.height_m / 2, -(ly + ry) / 2);
    // Плоскость смотрит по +z; поворот ставит её лицом по нормали стороны, и тогда её +x идёт
    // от левого края стены к правому, если смотреть снаружи.
    const [nx, ny] = w.normal;
    wall.rotation.y = Math.atan2(nx, -ny);
    this.scene.add(wall, this._edges(THREE, geo, wall.position).rotateY(wall.rotation.y));
    this._relief(THREE, w, wall.rotation.y);
    this.render();
  }

  // Выступы стены (цоколь, карниз, подоконник, козырёк, крыльцо): форму по классу и виду строит
  // Relief (house3d_relief.js) в осях стены — x от её левого края, y от земли, z наружу.
  _relief(THREE, w, turn) {
    const frame = new THREE.Group();
    const [[lx, ly], [rx, ry]] = [w.left, w.right];
    frame.position.set((lx + rx) / 2, 0, -(ly + ry) / 2);
    frame.rotation.y = turn;
    for (const r of w.relief) {
      if (!this.materials.has(r.color)) {
        this.materials.set(r.color, new THREE.MeshLambertMaterial({ color: r.color }));
      }
      for (const geo of this.relief.geometries(r, w)) {
        geo.translate(-w.length_m / 2, 0, 0);
        frame.add(new THREE.Mesh(geo, this.materials.get(r.color)), this._edges(THREE, geo));
      }
    }
    this.scene.add(frame);
  }

  _bind() {
    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const start = { x: e.clientX, y: e.clientY, view: { ...this.view } };
      el.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const k = 0.008;
        this.view.azimuth = start.view.azimuth - (ev.clientX - start.x) * k;
        this.view.elevation = Math.min(1.5, Math.max(0.02, start.view.elevation + (ev.clientY - start.y) * k));
        this.render();
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", () => el.removeEventListener("pointermove", move), { once: true });
    });
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = this.view.distance * Math.exp(e.deltaY * 0.0015);
      this.view.distance = Math.min(this.radius * 12, Math.max(this.radius * 0.8, d));
      this.render();
    }, { passive: false });
    el.addEventListener("dblclick", () => this.fit());
    this.observer = new ResizeObserver(() => this._resize());
    this.observer.observe(this.container);
  }

  // Отдать WebGL-контекст: у браузера их немного (на телефоне — около 8), а страница проверки
  // открывает по четыре дома на каждом шаге.
  dispose() {
    this.observer?.disconnect();
    this.renderer?.dispose();
    this.renderer?.forceContextLoss();
  }

  _resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }
}

// SVG стены → canvas в px_per_m. Размер в пикселях пишем в сам SVG: без width/height у него нет
// своего размера, Chromium растягивает его по viewBox, а WebKit (iPhone) берёт viewBox в метрах
// как пиксели (9×3 вместо 780×300), рисует поменьше, и поля текстуры остаются прозрачными —
// стены чёрные (gf#277).
async function rasterize(svg, lengthM, heightM, pxPerM) {
  const width = Math.round(lengthM * pxPerM), height = Math.round(heightM * pxPerM);
  const root = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement;
  root.setAttribute("width", width);
  root.setAttribute("height", height);
  const img = new Image();
  img.src = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(root)],
    { type: "image/svg+xml" }));
  await img.decode();
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d").drawImage(img, 0, 0, width, height);
  URL.revokeObjectURL(img.src);
  return canvas;
}
