// Дом объёмом: стены по контуру плана, фасад стороны — текстурой, крыша — плоская плита.
// Данные — /api/runs/<id>/house3d (render/house3d.py): метры плана, y вверх. В сцене three.js
// ось y — вверх, поэтому точка плана (x, y) стоит в (x, высота, −y).
// three.js грузится по адресу из config/viewer.toml только при открытии вкладки.

import { refusedFrom } from "/static/refusal.js";
import { Relief } from "/static/house3d_relief.js";
import { faceUV, pixels, wallScale, worldUV } from "/static/house3d_texture.js";

let threeModule = null;

export class HouseStage {
  // look — [house3d] из config/viewer.toml (через /api/options).
  constructor(container, look) {
    this.container = container;
    this.look = look;
    this.view = { azimuth: -0.6, elevation: 0.45, distance: 1 };
  }

  // Ответ смотрелки или отказ с причиной; общий у дома объёмом и у просмотра IFC.
  async _fetch(url) {
    const res = await fetch(url);
    if (!res.ok) throw await refusedFrom(res);
    return res;
  }

  async load(url) {
    await this.show(await (await this._fetch(url)).json());
  }

  // view — взгляд прежнего дома: после правки дом пересобирается с того же места.
  async show(data, view = null) {
    threeModule ??= await import(this.look.three_url);
    this._scene(threeModule, data);
    await this._tiles(threeModule, data.swatches);
    this._roof(threeModule, data);
    this._items(threeModule, data.items);
    this._ground(threeModule);
    this.pxPerM = this._wallScale(data.walls);
    await Promise.all(data.walls.map((w) => this._wall(threeModule, w)));
    this._bind();
    if (!view) return this.fit();
    this.view = { ...view };
    this.render();
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

  // Холст, камера и свет: общие у дома объёмом и у просмотра IFC (ifc_view.js).
  _canvas(THREE) {
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
  }

  _scene(THREE, data) {
    this._canvas(THREE);
    const xs = data.corners.map(([x]) => x), zs = data.corners.map(([, y]) => -y);
    const mid = (v) => (Math.min(...v) + Math.max(...v)) / 2;
    this.center = new THREE.Vector3(mid(xs), data.eaves_m / 2, mid(zs));
    this.radius = Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs), data.eaves_m) / 2;
    this.relief = new Relief(THREE, this.look, data.trim);
    this.materials = new Map();  // цвет или id материала → материал: выступов десятки, видов — единицы
    this.tiles = new Map();  // id материала → { texture, size_m } ячейки рисунка
  }

  // Шаг текстур стен — желаемый px_per_m, но чтобы стена влезла в MAX_TEXTURE_SIZE видеокарты и
  // не больше texture_max_px, а все стены вместе — в бюджет памяти (gf#353).
  _wallScale(walls) {
    const gl = this.renderer.getContext();
    const maxSide = Math.min(this.look.texture_max_px, gl.getParameter(gl.MAX_TEXTURE_SIZE));
    return wallScale(walls.map((w) => [w.length_m, w.height_m]), this.look.px_per_m, maxSide,
      this.look.texture_budget_mpx * 1e6);
  }

  // Ячейки рисунков материалов (swatches дома) → повторяющиеся текстуры: кровлю и выступы
  // выкладывают ими тем же шагом, что на листе. Ячейка мала, поэтому шаг — желаемый px_per_m.
  async _tiles(THREE, swatches) {
    await Promise.all(Object.entries(swatches).map(async ([id, s]) => {
      const canvas = await rasterize(s.svg, pixels(s.width_m, this.look.px_per_m),
        pixels(s.height_m, this.look.px_per_m));
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      this.tiles.set(id, { texture, size_m: [s.width_m, s.height_m] });
    }));
  }

  // Материал кровли или выступа: рисунок материала палитры, если он есть у дома, иначе цвет.
  _material(THREE, id, color, side) {
    const key = `${this.tiles.has(id) ? id : color}|${side ?? ""}`;
    if (!this.materials.has(key)) {
      const look = this.tiles.has(id) ? { map: this.tiles.get(id).texture } : { color };
      this.materials.set(key, new THREE.MeshLambertMaterial({ ...look, ...(side && { side }) }));
    }
    return this.materials.get(key);
  }

  _roof(THREE, data) {
    if (data.roof.faces.length) return this._slopes(THREE, data.roof);
    // Дом из частей разной высоты (gf#322): плита над каждой частью на её карнизе.
    const slabs = data.roof.slabs || [{ shape: data.roof.flat, height_m: data.eaves_m }];
    for (const { shape, height_m } of slabs) this._slab(THREE, shape, height_m, data.roof);
  }

  // Дымовая труба, желоб и водосточные трубы (gf#454): план (x, y) и высота → сцена (x, высота, −y).
  _items(THREE, items) {
    const at = ([x, y], h) => new THREE.Vector3(x, h, -y);
    const add = (geo, color, position) => {
      const mesh = new THREE.Mesh(geo, this._material(THREE, null, color));
      mesh.position.copy(position);
      mesh.add(this._edges(THREE, geo));  // рёбра — дочерние: повторяют поворот
      this.scene.add(mesh);
      return mesh;
    };
    for (const c of items.chimneys) {
      const shape = new THREE.Shape(c.footprint.map(([x, y]) => new THREE.Vector2(x, y)));
      const geo = new THREE.ExtrudeGeometry(shape, { depth: c.z1 - c.z0, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      add(geo, c.color, new THREE.Vector3(0, c.z0, 0));
    }
    for (const g of items.gutters) {
      const [a, b] = [at(g.a, g.z - g.size / 2), at(g.b, g.z - g.size / 2)];
      const geo = new THREE.BoxGeometry(a.distanceTo(b), g.size, g.size);
      const mesh = add(geo, g.color, a.clone().add(b).multiplyScalar(0.5));
      mesh.rotation.y = Math.atan2(g.b[1] - g.a[1], g.b[0] - g.a[0]);
    }
    for (const p of items.pipes) {
      const r = p.diameter / 2;
      add(new THREE.CylinderGeometry(r, r, p.z_top, 12), p.color, at(p.center, p.z_top / 2));
      const [from, to] = [at(p.center, p.z_top), at(p.elbow, p.z_top)];
      if (from.distanceTo(to) < 1e-6) continue;
      const elbow = add(new THREE.CylinderGeometry(r, r, from.distanceTo(to), 12), p.color,
        from.clone().add(to).multiplyScalar(0.5));
      elbow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), to.clone().sub(from).normalize());
    }
  }

  _slab(THREE, outline, height, roof) {
    const shape = new THREE.Shape(outline.map(([x, y]) => new THREE.Vector2(x, y)));
    const geo = new THREE.ExtrudeGeometry(shape, { depth: roof.thickness_m, bevelEnabled: false });
    geo.rotateX(-Math.PI / 2);  // (x, y) плана → (x, −z); выдавливание — вверх
    const slab = new THREE.Mesh(geo, this._material(THREE, roof.material, roof.color || this.look.roof));
    slab.position.y = height;
    this.scene.add(slab, this._edges(THREE, geo, slab.position));
  }

  // Скаты и стены над карнизом (gf#320): многоугольники (x, y плана, высота) → треугольники
  // (стены над карнизом выпуклые — веер, скаты — по плану); (x, y, h) плана → (x, h, −y) сцены, как у стен.
  _slopes(THREE, roof) {
    const parts = [[roof.faces, roof.material, roof.color || this.look.roof],
      [roof.above, roof.wall_material, roof.wall || this.look.roof],
      // окна во фронтоне (gf#321): стекло чуть перед гладким многоугольником фронтона
      [roof.windows || [], null, roof.glass],
      // мансардные окна (gf#456): рама и стекло на верху кровли, высоты уже с толщиной кровли
      [roof.skylight_frames || [], null, this.look.edges], [roof.skylights || [], null, roof.glass]];
    for (const [shapes, id, color] of parts) {
      const material = this._material(THREE, id, color, THREE.DoubleSide);
      for (const shape of shapes) {
        const lift = shapes === roof.faces ? roof.thickness_m : 0;  // грань ската — низ плиты (gf#447)
        const points = shape.map(([x, y, h]) => new THREE.Vector3(x, h + lift, -y));
        let tris = fan(points.map((_, i) => i));
        if (shapes === roof.faces) {
          // скат плоский, но после обрыва на стене соседней части не обязательно выпуклый: по плану
          const flat = shape.map(([x, y]) => new THREE.Vector2(x, y));
          tris = THREE.ShapeUtils.triangulateShape(flat, []).flat();
        }
        const geo = new THREE.BufferGeometry().setFromPoints(tris.map((i) => points[i]));
        geo.computeVertexNormals();
        if (this.tiles.has(id)) this._faceUV(THREE, geo, points, tris, this.tiles.get(id).size_m);
        this.scene.add(new THREE.Mesh(geo, material), this._edges(THREE, geo));
        if (lift) this._slopeBody(THREE, points, tris, lift, material);
      }
    }
  }

  // Толща ската (gf#447): points — верх плиты (грань, поднятая на t), низ — грань, торцы —
  // вертикальные четырёхугольники по всем рёбрам: внутренние спрятаны под соседними скатами.
  _slopeBody(THREE, points, tris, t, material) {
    const down = new THREE.Vector3(0, -t, 0);
    const low = points.map((p) => p.clone().add(down));
    const pos = [];
    const add = (...ps) => ps.forEach((p) => pos.push(p.x, p.y, p.z));
    tris.forEach((i) => add(low[i]));
    points.forEach((a, i) => {
      const j = (i + 1) % points.length;
      add(low[i], low[j], points[j], low[i], points[j], points[i]);
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geo.computeVertexNormals();
    this.scene.add(new THREE.Mesh(geo, material), this._edges(THREE, geo));
  }

  // UV по метрам рисунка: ряды идут по скату вверх, как на фасаде листа.
  _faceUV(THREE, geo, points, tris, tile) {
    const uv = faceUV(points.map((p) => [p.x, p.y, p.z]), [this.center.x, this.center.y, this.center.z], tile);
    const flat = tris.flatMap((i) => uv[i]);
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(flat, 2));
  }

  _ground(THREE) {
    const ground = new THREE.Mesh(new THREE.CircleGeometry(this.radius * 4, 48),
      new THREE.MeshLambertMaterial({ color: this.look.ground }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(this.center.x, -0.01, this.center.z);
    this.scene.add(ground);
  }

  _edges(THREE, geo, position) {
    if (!this.look.outline) return new THREE.Group();  // рёбра выключены в настройках
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: this.look.edges }));
    if (position) lines.position.copy(position);
    return lines;
  }

  // Обводка стены по её силуэту (x от левого края, высота), а не по прямоугольнику плоскости:
  // выше ступени текстура прозрачна, а рамка висела бы над нижней частью и шла по её крыше (gf#431).
  _outline(THREE, w) {
    if (!this.look.outline) return new THREE.Group();
    const ring = w.outline || [[0, 0], [w.length_m, 0], [w.length_m, w.height_m], [0, w.height_m]];
    const points = ring.map(([x, y]) => new THREE.Vector3(x - w.length_m / 2, y - w.height_m / 2, 0));
    return new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial({ color: this.look.edges }));
  }

  async _wall(THREE, w) {
    const canvas = await rasterize(w.svg, pixels(w.length_m, this.pxPerM), pixels(w.height_m, this.pxPerM));
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const geo = new THREE.PlaneGeometry(w.length_m, w.height_m);
    const wall = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: texture, alphaTest: 0.5 }));
    const [[lx, ly], [rx, ry]] = [w.left, w.right];
    wall.position.set((lx + rx) / 2, w.height_m / 2, -(ly + ry) / 2);
    // Плоскость смотрит по +z; поворот ставит её лицом по нормали стороны, и тогда её +x идёт
    // от левого края стены к правому, если смотреть снаружи.
    const [nx, ny] = w.normal;
    wall.rotation.y = Math.atan2(nx, -ny);
    const outline = this._outline(THREE, w);
    outline.position.copy(wall.position);
    outline.rotation.y = wall.rotation.y;
    this.scene.add(wall, outline);
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
      const material = this._material(THREE, r.material, r.color);
      for (const raw of this.relief.geometries(r, w)) {
        const geo = this.tiles.has(r.material) ? this._worldUV(THREE, raw, this.tiles.get(r.material).size_m) : raw;
        geo.translate(-w.length_m / 2, 0, 0);
        frame.add(new THREE.Mesh(geo, material), this._edges(THREE, geo));
      }
    }
    this.scene.add(frame);
  }

  // UV выступа в метрах стены, делённых на ячейку рисунка: шов выступа идёт тем же шагом, что на
  // стене. Индексы разворачиваем: у граней коробки одни вершины на разные плоскости.
  _worldUV(THREE, geo, [tileW, tileH]) {
    const out = geo.index ? geo.toNonIndexed() : geo;
    const uv = worldUV(out.attributes.position.array);
    out.setAttribute("uv", new THREE.BufferAttribute(uv.map((x, i) => x / (i % 2 ? tileH : tileW)), 2));
    return out;
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

// Веер треугольников выпуклого многоугольника: вершина 0 и пары соседних.
function fan(points) {
  const out = [];
  for (let i = 1; i + 1 < points.length; i++) out.push(points[0], points[i], points[i + 1]);
  return out;
}

// SVG → canvas width × height пикселей. Размер в пикселях пишем в сам SVG: без width/height у него нет
// своего размера, Chromium растягивает его по viewBox, а WebKit (iPhone) берёт viewBox в метрах
// как пиксели (9×3 вместо 780×300), рисует поменьше, и поля текстуры остаются прозрачными —
// стены чёрные (gf#277).
async function rasterize(svg, width, height) {
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
