"""Выводимые элементы проёма (gf#212, `facade: Состав фасада по уровням`): модель ставит у проёма
признак, прямоугольник подоконника, наличника, ставен и козырька считает код (derive.py)."""

import pytest

from genfacade import derive, guidelines
from genfacade.datasets.synthetic import build
from genfacade.schema import EPS, Element, ElementClass, GuidelineCheck, Mode, Trim
from genfacade.snap import snap
from genfacade.train import tokens

SEEDS = range(40)


@pytest.fixture(scope="module")
def answers(cfg):
    """Синтетические дома как ответ модели: записаны токенами и разобраны (оба режима)."""
    out = []
    for seed in SEEDS:
        sheet = build.sample(seed, cfg).sheet
        for mode in Mode:
            answer = tokens.answer(sheet, mode, cfg)
            out.append((answer, tokens.decode(answer, tokens.bare(sheet), cfg)))
    return out


def _children(f, parent: Element, cls: ElementClass) -> list[Element]:
    return [e for e in f.elements if e.cls is cls and e.parent == parent.id]


def _of(f, cls: ElementClass) -> list[Element]:
    return [e for e in f.elements if e.cls is cls]


def test_sill_under_window_wider_by_overhang(answers, cfg):
    """У каждого окна с признаком подоконника — подоконник под ним: верх — низ окна, по ширине —
    окно плюс свес вида дома с каждой стороны."""
    sills = 0
    for answer, sheet in answers:
        look = cfg.derive.sill.get(sheet.spec.trim.sill)
        for f in sheet.facades:
            for w in _of(f, ElementClass.WINDOW):
                for s in _children(f, w, ElementClass.SILL):
                    assert s.y_m + s.h_m == pytest.approx(w.y_m)
                    assert s.x_m == pytest.approx(w.x_m - look.overhang_m)
                    assert s.w_m == pytest.approx(w.w_m + 2 * look.overhang_m)
                    assert s.h_m == pytest.approx(look.height_m)
                    sills += 1
        # подоконник — у каждого окна с признаком, а не только там, где он вывелся
        assert answer.count(tokens.tok(Trim.SILL)) == sum(
            len(_of(f, ElementClass.SILL)) for f in sheet.facades)
    assert sills > 0


def test_canopy_over_door(answers, cfg):
    """У двери с признаком козырька — козырёк над ней: шире двери на свес с каждой стороны (в
    пределах стены), от верха двери — зазор вида дома, не выше карниза."""
    canopies = 0
    for answer, sheet in answers:
        for f in sheet.facades:
            for d in _of(f, ElementClass.DOOR):
                for k in _children(f, d, ElementClass.CANOPY):
                    look = cfg.derive.canopy.of(sheet.spec.trim.canopy)
                    assert k.y_m == pytest.approx(d.y_m + d.h_m + look.gap_m)
                    assert k.x_m == pytest.approx(max(0.0, d.x_m - look.pad_m))
                    assert k.x_m + k.w_m == pytest.approx(
                        min(f.side.length_m, d.x_m + d.w_m + look.pad_m))
                    assert cfg.derive.canopy.min_h_m - EPS <= k.h_m <= look.height_m + EPS
                    assert k.y_m + k.h_m <= sheet.spec.eaves_m + EPS
                    canopies += 1
        assert answer.count(tokens.tok(Trim.CANOPY)) == sum(
            len(_of(f, ElementClass.CANOPY)) for f in sheet.facades)
    assert canopies > 0


def test_shutters_half_window_beside_frame(answers, cfg):
    """Ставни — пара по бокам окна шириной половину окна, высотой окна, вплотную к раме или
    наличнику, в пределах стены и не на соседнем проёме (shutter_width_us)."""
    pairs = 0
    for _, sheet in answers:
        for f in sheet.facades:
            for w in _of(f, ElementClass.WINDOW):
                blinds = sorted(_children(f, w, ElementClass.BLIND), key=lambda b: b.x_m)
                if not blinds:
                    continue
                casing = _children(f, w, ElementClass.MOLDING)
                off = w.x_m - casing[0].x_m if casing else 0.0
                left, right = blinds
                assert left.x_m + left.w_m == pytest.approx(w.x_m - off)
                assert right.x_m == pytest.approx(w.x_m + w.w_m + off)
                half = pytest.approx(cfg.derive.shutters.share * w.w_m)
                assert [b.w_m for b in blinds] == [half, half]
                assert all((b.y_m, b.h_m) == (w.y_m, w.h_m) for b in blinds)
                assert left.x_m >= -EPS and right.x_m + right.w_m <= f.side.length_m + EPS
                pairs += 1
    assert pairs > 0


def test_house_has_no_more_window_sizes_than_types(cfg):
    """У синтетического дома окон разных размеров не больше window_types: ответ модели их
    передаёт без потерь."""
    for seed in SEEDS:
        sheet = build.sample(seed, cfg).sheet
        sizes = {(w.w_m, w.h_m) for f in sheet.facades for w in _of(f, ElementClass.WINDOW)}
        assert len(sizes) <= tokens.window_types(cfg), seed


def test_trims_follow_their_window_when_snapped(answers, cfg):
    """Привязка двигает окно — подоконник, наличник, ставни едут и тянутся с ним так же, как их
    поставил бы вывод (snap.py)."""
    def stacked(f) -> list[Element]:  # окна со ставнями, над или под которыми — окно на той же оси
        ws = _of(f, ElementClass.WINDOW)
        return [w for w in ws if _children(f, w, ElementClass.BLIND) and any(
            v is not w and abs(v.x_m - w.x_m) < EPS and v.w_m == w.w_m for v in ws)]

    sheet = next(s for _, s in answers if any(stacked(f) for f in s.facades))
    f = next(f for f in sheet.facades if stacked(f))
    w = stacked(f)[0]
    wall = derive.Wall(sheet.spec, f.side.length_m, cfg.derive)
    nudged = [e.model_copy(update={"x_m": e.x_m + 0.02, "w_m": e.w_m - 0.04, "fixed": []})
              if e.id == w.id else e for e in derive.base(f.elements)]
    moved = f.model_copy(update={"elements": derive.place(nudged, derive.flags(f.elements), wall)})
    back = snap(sheet.model_copy(update={"facades": [moved]}), cfg.checks).facades[0]
    snapped = next(e for e in back.elements if e.id == w.id)
    assert abs(snapped.x_m - (w.x_m + 0.02)) > EPS  # привязка окно сдвинула — к оси соседа
    again = derive.place(derive.base(back.elements), derive.flags(back.elements), wall)
    by_id = {e.id: e for e in again}
    for e in back.elements:
        assert (e.x_m, e.y_m, e.w_m, e.h_m) == pytest.approx(
            (by_id[e.id].x_m, by_id[e.id].y_m, by_id[e.id].w_m, by_id[e.id].h_m)), e.id


def test_frieze_counts_from_cornice_and_casing(cfg):
    """`window_head_to_eaves`: зазор — от верха окна с наличником до низа карниза. Окно с верхом
    на 0,4 м ниже отметки карниза под карнизом 0,25 м — прижато (0,15 < 0,2)."""
    rule = next(g for g in cfg.guidelines.guideline if g.check is GuidelineCheck.HEAD_TO_EAVES)
    sheet = build.sample(0, cfg).sheet
    f = sheet.facades[0]
    top = sheet.spec.eaves_m - 0.4
    window = Element(id="w", cls=ElementClass.WINDOW, x_m=1.0, y_m=top - 1.3, w_m=1.0, h_m=1.3,
                     floor=sheet.spec.floors)
    cornice = Element(id="c", cls=ElementClass.CORNICE, x_m=0.0, y_m=sheet.spec.eaves_m - 0.25,
                      w_m=f.side.length_m, h_m=0.25)
    one = sheet.model_copy(update={"facades": [f.model_copy(update={
        "elements": [window, cornice]})]})
    assert guidelines.cases(rule, one, None) == [False]
    bare = sheet.model_copy(update={"facades": [f.model_copy(update={"elements": [window]})]})
    assert guidelines.cases(rule, bare, None) == [True]     # без карниза — до отметки, 0,4 м


def test_synthetic_windows_keep_frieze(cfg):
    """Синтетика: у окна верхнего этажа до низа карниза — фриз из свода (gf#212: окна gf#211
    упирались в карниз)."""
    rule = next(g for g in cfg.guidelines.guideline if g.check is GuidelineCheck.HEAD_TO_EAVES)
    for seed in SEEDS:
        assert all(guidelines.cases(rule, build.sample(seed, cfg).sheet, None)), seed
