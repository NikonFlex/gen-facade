// Дом в BIM (gf#392): файл IFC4 из /api/runs/<id>/house.ifc разбирает web-ifc (wasm, из
// config/viewer.toml, грузится только при открытии вкладки), объекты рисует тот же three.js, что у
// дома объёмом. Щелчок по объекту — его тип, имя и свойства из файла; сверху — сколько объектов
// каких типов в файле. web-ifc сам переворачивает IFC (z вверх) в y вверх: точка (x, y, z) файла стоит в (x, z, −y),
// как у дома объёмом.

import { HouseStage } from "/static/house3d.js";

const TYPES = [["IFCBUILDINGSTOREY", "этажи"], ["IFCWALL", "стены"], ["IFCWINDOW", "окна"],
  ["IFCDOOR", "двери"], ["IFCSLAB", "плиты"], ["IFCROOF", "крыша"], ["IFCOPENINGELEMENT", "проёмы"]];
const CLICK_PX = 4;  // сдвиг указателя больше этого — это вращение, а не щелчок

let webIfc = null;

export class IfcStage extends HouseStage {
  constructor(container, look, panel) {
    super(container, look);
    this.panel = panel;
    this.meshes = [];
  }

  async load(url) {
    const bytes = new Uint8Array(await (await this._fetch(url)).arrayBuffer());
    const THREE = (this.THREE ??= await import(this.look.three_url));
    webIfc ??= await import(this.look.web_ifc_url);
    const api = new webIfc.IfcAPI();
    api.SetWasmPath(this.look.web_ifc_wasm_dir, true);
    await api.Init();
    this.api = api;
    this.model = api.OpenModel(bytes);
    this._ifcScene(THREE);
    this._meshes(THREE);
    this._frame(THREE);
    this._ground(THREE);
    this._bind();
    this._pick(THREE);
    this._summary();
    this.fit();
  }

  _ifcScene(THREE) {
    this._canvas(THREE);
    this.house = new THREE.Group();  // web-ifc уже отдаёт y вверх: (x, y, z) файла → (x, z, −y)
    this.scene.add(this.house);
  }

  // Объекты файла — по одному мешу на каждую геометрию; проёмы (вырезы) не рисуем.
  _meshes(THREE) {
    const opening = webIfc.IFCOPENINGELEMENT;
    this.api.StreamAllMeshes(this.model, (mesh) => {
      if (this.api.GetLineType(this.model, mesh.expressID) === opening) return;
      for (let i = 0; i < mesh.geometries.size(); i++) {
        const placed = mesh.geometries.get(i);
        const geo = this.api.GetGeometry(this.model, placed.geometryExpressID);
        const verts = this.api.GetVertexArray(geo.GetVertexData(), geo.GetVertexDataSize());
        const index = this.api.GetIndexArray(geo.GetIndexData(), geo.GetIndexDataSize());
        const buffer = new THREE.InterleavedBuffer(verts, 6);
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.InterleavedBufferAttribute(buffer, 3, 0));
        g.setAttribute("normal", new THREE.InterleavedBufferAttribute(buffer, 3, 3));
        g.setIndex(new THREE.BufferAttribute(index, 1));
        const { x, y, z, w } = placed.color;
        const material = new THREE.MeshLambertMaterial({
          color: new THREE.Color().setRGB(x, y, z, THREE.SRGBColorSpace), side: THREE.DoubleSide,
          transparent: w < 1, opacity: w });
        const m = new THREE.Mesh(g, material);
        m.applyMatrix4(new THREE.Matrix4().fromArray(placed.flatTransformation));
        m.userData.expressID = mesh.expressID;
        this.meshes.push(m);
        this.house.add(m);
        geo.delete();
      }
    });
  }

  _frame(THREE) {
    this.house.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.house);
    this.center = box.getCenter(new THREE.Vector3());
    this.radius = box.getSize(new THREE.Vector3()).length() / 2;
    this.house.position.y -= box.min.y;  // низ дома — на земле
    this.center.y -= box.min.y;
  }

  // Щелчок (без сдвига) — луч в сцену, ближайший объект IFC подсвечивается, панель — его свойства.
  _pick(THREE) {
    const el = this.renderer.domElement, ray = new THREE.Raycaster();
    let down = null;
    el.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > CLICK_PX) return;
      const r = el.getBoundingClientRect();
      ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
        -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
      const hit = ray.intersectObjects(this.meshes, false)[0];
      this._select(hit ? hit.object.userData.expressID : null);
    });
  }

  _select(id) {
    this.selected = id;
    for (const m of this.meshes) {
      const on = m.userData.expressID === id;
      m.material.emissive?.set(on ? this.look.selected : 0x000000);
      m.material.emissiveIntensity = on ? 0.6 : 0;
    }
    this.render();
    this._details(id);
  }

  // Сводка файла: сколько объектов каждого типа — то, что видит и любой другой просмотрщик IFC.
  _summary() {
    this.counts = TYPES.map(([type, title]) =>
      [title, this.api.GetLineIDsWithType(this.model, webIfc[type]).size()]);
    this._details(null);
  }

  _details(id) {
    const box = this.panel;
    box.replaceChildren();
    const add = (tag, text, cls) => {
      const node = Object.assign(document.createElement(tag), { textContent: text });
      if (cls) node.className = cls;
      box.append(node);
    };
    add("h3", "IFC4 · объекты файла");
    add("p", this.counts.map(([title, n]) => `${title}: ${n}`).join(" · "), "ifc-counts");
    if (id === null) return add("p", "Щёлкните по стене, окну, двери или плите — тип и свойства.", "ifc-hint");
    const line = this.api.GetLine(this.model, id);
    add("h3", `${this.api.GetNameFromTypeCode(line.type)} · ${line.Name?.value ?? ""}`);
    add("p", `GlobalId: ${line.GlobalId?.value ?? ""}`, "ifc-prop");
    this._psets(id, add);
  }

  // Наборы свойств читает web-ifc асинхронно; пока читал, выбрали другой объект — панель не трогаем.
  async _psets(id, add) {
    let sets = [];
    try {
      sets = await this.api.properties.getPropertySets(this.model, id, true);
    } catch (err) {
      return add("p", "Свойства не прочитаны", "ifc-hint");
    }
    if (this.selected !== id) return;
    for (const set of sets) {
      add("h4", set.Name?.value ?? "");
      for (const p of set.HasProperties ?? []) add("p", `${p.Name?.value}: ${p.NominalValue?.value}`, "ifc-prop");
    }
  }

  dispose() {
    super.dispose();
    this.api?.CloseModel(this.model);
  }
}
