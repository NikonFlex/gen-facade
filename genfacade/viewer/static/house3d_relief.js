// Формы выступов стены для дома объёмом (gf#305): цоколь с отливом, карниз ступенями, подоконник
// с уклоном, козырёк трёх видов, крыльцо со ступенями. Форму выбирают класс и вид выступа из
// /api/runs/<id>/house3d (render/house3d.py); размеры — [house3d] и [trim] конфига.
// Оси стены: x — от её левого края, y — от земли, z — наружу. Класс возвращает геометрии
// three.js уже в этих осях; цвет и рёбра ставит вызывающий.

const EDGE = 0.01;  // м: рамка у края стены считается доходящей до угла

// Выступ → метод формы: у зоны ключ — её роль, у элемента — класс. Остальное — коробка.
const FORMS = { plinth: "plinth", cornice: "cornice", sill: "sill", canopy: "canopy", porch: "porch" };

export class Relief {
  // look — [house3d], trim — [trim] листа (размеры плиты и кронштейнов козырька).
  constructor(THREE, look, trim) {
    this.THREE = THREE;
    this.look = look;
    this.trim = trim;
  }

  // w — стена из данных: length_m и convex_left. Геометрии — в осях стены с началом в её левом краю.
  geometries(r, w) {
    return this[FORMS[r.role ?? r.cls] ?? "plain"](r, w);
  }

  // Левый край рамки. У края стены соседние выступы сходятся без щели и нахлёста: на выпуклом
  // углу левая стена выходит вперёд на `reach` (вынос профиля), правая кончается на углу; на
  // вогнутом левая стена не доходит до соседней на тот же `reach`.
  _start(r, w, reach) {
    if (r.x0 > EDGE) return r.x0;
    return w.convex_left ? -reach : reach;
  }

  plain(r, w) {
    return [this._box(this._start(r, w, r.depth), r.x1, r.y0, r.y1, 0, r.depth)];
  }

  // Цоколь: коробка, верх — отливом: внешняя грань ниже верха на plinth_wash_m.
  plinth(r, w) {
    const wash = Math.min(this.look.plinth_wash_m, r.y1 - r.y0);
    const d = r.depth;
    return [this._extrudeX([[0, r.y0], [d, r.y0], [d, r.y1 - wash], [0, r.y1]],
      this._start(r, w, d), r.x1)];
  }

  // Карниз: ступени снизу вверх, вынос растёт — по cornice_steps. Каждая ступень выходит за угол
  // на свой вынос, поэтому на углу профиль продолжается без перелома.
  cornice(r, w) {
    const steps = this.look.cornice_steps, h = r.y1 - r.y0;
    return steps.map(([reach, from], i) => {
      const to = i + 1 < steps.length ? steps[i + 1][1] : 1;
      return this._box(this._start(r, w, reach * r.depth), r.x1,
        r.y0 + from * h, r.y0 + to * h, 0, reach * r.depth);
    });
  }

  // Подоконник: flat — тонкая полка, sloped — плита с отливом (уклон наружу).
  sill(r, w) {
    return r.kind === "sloped" ? this._wedge(r, w) : this.plain(r, w);
  }

  // Козырёк над дверью: gable — двускатный фронтоном наружу, bracket — плита на двух кронштейнах,
  // иначе (flat) — плита с уклоном от стены.
  canopy(r, w) {
    if (r.kind === "gable") return [this._gable(r)];
    if (r.kind === "bracket") return this._bracketed(r);
    return this._wedge(r, w);
  }

  // Крыльцо: площадка у двери глубиной depth и ступени перед ней. Профиль — лестница: ступеней
  // `steps` (считает render/house3d.py), высота каждой — доля высоты крыльца.
  porch(r, w) {
    const n = r.steps, d = r.depth, rise = (r.y1 - r.y0) / n;
    const out = (k) => d + (n - k) * this.look.tread_m;  // на сколько выходит верх k-й ступени
    const profile = [[0, r.y0], [out(1), r.y0]];
    for (let k = 1; k <= n; k++) {
      profile.push([out(k), r.y0 + k * rise]);
      if (k < n) profile.push([out(k + 1), r.y0 + k * rise]);
    }
    profile.push([0, r.y1]);
    return [this._extrudeX(profile, this._start(r, w, d), r.x1)];
  }

  _wedge(r, w) {
    const d = r.depth, h = r.y1 - r.y0;
    return [this._extrudeX([[0, r.y0], [d, r.y0], [d, r.y0 + h * this.look.slope_edge], [0, r.y1]],
      this._start(r, w, d), r.x1)];
  }

  _gable(r) {
    const THREE = this.THREE;
    const shape = new THREE.Shape([new THREE.Vector2(r.x0, r.y0), new THREE.Vector2(r.x1, r.y0),
      new THREE.Vector2((r.x0 + r.x1) / 2, r.y1)]);
    return new THREE.ExtrudeGeometry(shape, { depth: r.depth, bevelEnabled: false });
  }

  _bracketed(r) {
    const { slab_m, bracket_at, bracket_w_m } = this.trim;
    const top = r.y1 - Math.min(slab_m, r.y1 - r.y0), width = r.x1 - r.x0;
    const struts = [r.x0 + width * bracket_at, r.x1 - width * bracket_at].map((at) =>
      this._extrudeX([[0, r.y0], [0, top], [r.depth, top]], at - bracket_w_m / 2, at + bracket_w_m / 2));
    return [this._box(r.x0, r.x1, top, r.y1, 0, r.depth), ...struts];
  }

  _box(x0, x1, y0, y1, z0, z1) {
    return new this.THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0)
      .translate((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
  }

  // Профиль в плоскости (z, y), вытянутый вдоль стены от x0 до x1. Выдавливание three.js идёт
  // по своей оси z, поэтому профиль кладём как (−z, y) и поворачиваем вокруг y: ось выдавливания
  // становится осью x стены, а −z профиля — осью z наружу.
  _extrudeX(profile, x0, x1) {
    const THREE = this.THREE;
    const shape = new THREE.Shape(profile.map(([z, y]) => new THREE.Vector2(-z, y)));
    return new THREE.ExtrudeGeometry(shape, { depth: x1 - x0, bevelEnabled: false })
      .rotateY(Math.PI / 2).translate(x0, 0, 0);
  }
}
