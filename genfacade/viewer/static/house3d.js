// Дом объёмом: стены по контуру плана, фасад стороны — текстурой, крыша — плоская плита.
// Данные — /api/runs/<id>/house3d (render/house3d.py): метры плана, y вверх. В сцене three.js
// ось y — вверх, поэтому точка плана (x, y) стоит в (x, высота, −y).
// three.js грузится по адресу из config/viewer.toml только при открытии вкладки.

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
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail ?? "дом не собран");
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
    this._roof(THREE, data);
    this._ground(THREE);
  }

  _roof(THREE, data) {
    const shape = new THREE.Shape(data.corners.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ExtrudeGeometry(shape, { depth: ROOF_M, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);  // (x, y) плана → (x, −z); выдавливание — вверх
    const roof = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color: this.look.roof }));
    roof.position.y = data.eaves_m;
    this.scene.add(roof, this._edges(THREE, geo, roof.position));
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
    lines.position.copy(position);
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
    this.render();
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
    new ResizeObserver(() => this._resize()).observe(this.container);
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

// SVG стены → canvas в px_per_m: картинка без width/height растягивается по viewBox.
async function rasterize(svg, lengthM, heightM, pxPerM) {
  const img = new Image();
  img.src = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  await img.decode();
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(lengthM * pxPerM);
  canvas.height = Math.round(heightM * pxPerM);
  canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(img.src);
  return canvas;
}
