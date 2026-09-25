# Литература

Обновлено: 2026-09-25

Статус: `не читано` → `просмотрено` (абстракт/скимминг) → `прочитано` (можно цитировать).
Перед внесением в текст диплома **сверить выходные данные с первоисточником** —
приведённые ниже метаданные местами восстановлены не из самой статьи.

## Приоритет чтения

1. **EvoVec** — статья научрука, надо знать досконально
2. **DeepSVG** и **FloorplanGAN** — методологические образцы
3. **Pro-DG** — ближе всех к нашей задаче
4. **DiffVG**, **LIVE** — альтернативы векторизации для сравнения
5. Обзор 2026 по generative AI в дизайне фасадов — каркас для главы обзора

---

## Векторизация

### EvoVec: Evolutionary Image Vectorization with Adaptive Curve Number and Color Gradients
Bazhenov, Jarsky, Efimova, Muravyov · Springer, 2024 · `10.1007/978-3-031-70085-9_24`
Статус: **не читано**. Приоритет 1 — статья Егора, он сам её порекомендовал.

Идея: итеративное улучшение векторного изображения мутациями и кроссовером `[из абстракта]`.
Заявлено: не требует параметров кроме исходного изображения, умеет работать с цветовыми
градиентами, обходит конкурентов по попиксельному MSE на 15% `[из абстракта]`.
Поддержано ИТМО, проект 623097 `[из абстракта]`. Реализация заявлена как публично доступная.

> TODO: найти репозиторий EvoVec, проверить, что запускается.

Есть более ранняя работа той же линии: «Evolutionary image vectorization with variable
curve number», `10.1145/3638530.3664171` `[не проверено]`.

### DiffVG — Differentiable Vector Graphics Rasterization for Editing and Learning
Li et al. `[не проверено: авторы и год уточнить]`
Статус: **не читано**. Рекомендован Егором.
Дифференцируемая растеризация, позволяет оптимизировать параметры SVG по градиенту
от растрового лосса. База для большинства ML-подходов к векторизации.

### LIVE — Towards Layer-wise Image Vectorization
`[не проверено: авторы, год, venue уточнить]`
Статус: **не читано**. Рекомендован Егором.
Послойная векторизация с постепенным наращиванием числа примитивов.

---

## Генерация векторной графики

### DeepSVG: A Hierarchical Generative Network for Vector Graphics
https://github.com/alexandre01/deepsvg
Статус: **не читано**. Из ТЗ, помечено как «основы генерации SVG, но у нас много наработок».
Иерархическая генеративная модель для SVG. Базовый ориентир для пути A.

### FloorplanGAN: Vector residential floorplan adversarial generation
`10.1016/j.autcon.2022.104470`
Статус: **не читано**. В ТЗ помечено «по методологии» — то есть смотреть на постановку
эксперимента и набор метрик, а не только на метод.

### Leveraging Large Language Models For Scalable Vector Graphics Processing: A Review
https://arxiv.org/abs/2503.04983
Статус: **не читано**. Найдено самостоятельно. Релевантно совету Егора смотреть на
LLM-модели для генерации SVG напрямую.

---

## Фасады: генерация и представление

### Pro-DG: Procedural Diffusion Guidance for Architectural Facade Generation
https://arxiv.org/abs/2504.01571
Статус: **не читано**. Похоже, ближайшая к нашей задаче работа: использует иерархическую
структуру фасада для управляемой генерации. Прочитать рано — чтобы понять,
что уже сделано и чем отличаться.

### A graph-enabled parametric modeling approach for façade layout generative design
`10.1016/j.jobe.2025.112481`
Статус: **не читано**. Графовое представление пространственных связей между элементами
фасада — прямо релевантно разделу «формальное представление».

### Inverse Procedural Modeling of Facade Layouts
Wu et al. · ACM TOG, 2014 · `10.1145/2601097.2601162`
Статус: **не читано**. Классика: вывод процедурных правил из готовой раскладки фасада.
Полезно для понимания, как формально описывают регулярность и повторяемость.

### A Deep Learning-Based Approach to Generating Comprehensive Building Façades for Low-Rise Housing
https://www.mdpi.com/2071-1050/15/3/1816
Статус: **не читано**. В ТЗ помечено «ранняя, базовая».

### Generative artificial intelligence in building facade design: Models, applications, and future directions
`10.1016/j.buildenv.2026.115041`
Статус: **не читано**. Свежий обзор — самый быстрый способ построить каркас главы обзора
и увидеть, кто ещё чем занимается. Хороший кандидат прочитать вторым после EvoVec.

---

## Чего в списке нет и стоит поискать

- работы по **structure-aware / regularized векторизации** — прямо по нашей гипотезе вклада
  (см. [methods.md](methods.md)); если их нет, это аргумент о новизне
- обнаружение регулярных решёток и повторяющихся структур на изображениях
  (lattice / repetition detection)
- shape grammars для фасадов — в ТЗ упомянуты, но ни одной ссылки не дано
- метрики качества векторизации и валидности SVG

---

# Обзор состояния области (поиск 2026-09-25)

Проведён систематический поиск по 35 запросам (список в конце раздела).
**Вывод: ниша свободна, но плотно окружена.** Две работы подходят вплотную
с разных сторон, и обе — от одной группы.

## ⚠ Что заявлять о новизне НЕЛЬЗЯ

**«Впервые учим структуру фасада вместо рукописных правил» — занято.**

- **FaçAID: A Transformer Model for Neuro-Symbolic Facade Reconstruction** ·
  Plocharski, Swidzinski, Porter-Sobieraj, Musialski · **SIGGRAPH Asia 2024** ·
  https://arxiv.org/abs/2406.01829 `[проверено: страница arXiv]`
  Авторегрессионный трансформер: вход — сегментированный фасад, выход — процедурное
  определение в собственной split-грамматике. **Текстом не управляется, выход —
  грамматика, а не вектор, задача — реконструкция существующего фасада, а не
  генерация нового. Обучен на синтетике от рукописной грамматики.**
- Ещё раньше: **Bayesian Grammar Learning for Inverse Procedural Modeling** ·
  Martinović, Van Gool · CVPR 2013 `[не проверено]`. Учит грамматику из размеченных
  фасадов, грамматику можно сэмплировать и получать новые фасады.

**«Впервые накладываем ограничение регулярности на боксы фасада» — тоже занято.**

- **Beyond Segmentation: Structurally Informed Facade Parsing from Imperfect Images** ·
  Janicki, Plocharski, Musialski · **EUROGRAPHICS 2026 Short Paper** ·
  https://arxiv.org/abs/2604.09260 `[проверено: страница arXiv]`
  YOLOv8 плюс собственный лёгкий **alignment loss**, поощряющий решётчатую
  согласованность боксов. **Эксперименты на CMP.** Но это **парсинг** (image → boxes),
  не генерация; текста нет, SVG нет.
  Отсюда надо забрать формулировку лосса и подход к оценке регулярности —
  и честно процитировать как ближайшего соседа.

## Что остаётся нашим

Свободна именно **комбинация**: структура фасада **выучена из размеченных данных**
+ **управляется текстовым описанием** + **выход векторный** (классифицированные
прямоугольники → SVG) + **регулярность проверяема метриками**.

Формулировать новизну надо так, а не как «первыми учим структуру» — на защите поймают.

Подтверждение из свежего обзора: **Aghimien, Aksamija. Generative Artificial
Intelligence in Building Facade Design** · Building and Environment, 2026 ·
`10.1016/j.buildenv.2026.115041` `[из вторичного источника, полный текст не открыт]` —
констатирует, что «image-based data type dominates both model input and output»,
среди пробелов называет «limited adoption of geometry-aware workflows».
Векторный выход и текстовое управление структурой в перечне направлений
не упомянуты вообще.

> **Достать полный текст обзора и процитировать дословно** — это лучший аргумент
> о пробеле, какой у нас есть.

## ⚠ Главный риск: группа Plocharski–Musialski

Warsaw UT / NJIT публикуется по фасадам каждые несколько месяцев:
FaçAID (SIGGRAPH Asia 2024), постер SIGGRAPH 2025, Pro-DG (CGF 2026),
EG 2026 Short. У них уже есть и выученная структура, и alignment loss,
и работа с CMP. **Логичный следующий шаг с их стороны — как раз текст и вектор.**

Тему менять не надо, но за их arXiv надо следить регулярно.

## Что переиспользовать технически

Все — `[не проверено]`, найдены агентом, первоисточники не открывались:

| Работа | Чем полезна |
|---|---|
| DesigNet: Learning to Draw Vector Graphics as Designers Do · arXiv:2604.06494 | **снэппинг к осям внутри генеративной векторной модели**, дифференцируемо через straight-through estimator. Готовый рецепт жёсткого геометрического ограничения |
| Structural Evaluation Metrics for SVG Generation · arXiv:2604.08809 | метрики Purity/Coverage/Compactness/Locality над элементами SVG |
| SketchGen: Generating Constrained CAD Sketches · NeurIPS 2021 | формализм «примитив + ограничение как токены» — альтернатива нашему представлению |
| Tell2Design · ACL 2023, arXiv:2311.15941 | 80k+ планировок с текстовыми инструкциями. **Прямой аналог нашей задачи в соседнем домене.** Для фасадов такого датасета нет — это и новизна, и работа |
| DiffPlanner · arXiv:2508.13738 | содержит цитату против растрового промежуточного шага: «converting vector→raster→vector ... often resulting in information loss» |
| Канон layout-метрик: LayoutTransformer, LayoutDM, LayoutDiffusion | **Alignment** (6 типов выравнивания), **Overlap**, mIoU, FID над layout-фичами — готовый набор для группы метрик «геометрическая корректность» |

## Целенаправленно искали и НЕ нашли

Это аргументы о новизне, их надо уметь предъявить:

- генеративной модели, выдающей фасад как SVG или набор классифицированных прямоугольников;
- любого текстового обусловливания **структуры** фасада — текст в фасадах встречается
  только как условие для растровой диффузии;
- векторизации с ограничением на повторяемость и решётчатую регулярность —
  в векторизации есть топология, слои, снэппинг к осям, решётки нет;
- датасета «текст ↔ раскладка фасада», аналога Tell2Design для фасадов;
- открытого репозитория по facade layout generation в вектор.

<details>
<summary>35 поисковых запросов (для раздела о новизне в тексте ВКР)</summary>

`facade layout generation neural network structured output not pixels` ·
`text-conditioned facade generation vector layout deep learning` ·
`structure-aware image vectorization geometric constraints alignment parallelism` ·
`inverse procedural modeling facade deep learning grammar induction` ·
`Plocharski Musialski facade procedural 2025 grammar transformer` ·
`"facade" generation "layout" transformer bounding boxes windows learned from data arXiv` ·
`layout generation alignment loss metric regularity overlap graphic layout evaluation metrics` ·
`text to SVG generation large language model vector graphics architectural drawing` ·
`vectorized floorplan generation graph-constrained transformer 2024` ·
`SVG generation geometric constraints diffusion transformer CAD sketch parametric` ·
`lattice detection repeated structure facade regularity symmetry detection` ·
`generative model building facade window placement grid regularity deep learning vector output 2025 2026` ·
`raster to vector regularization architectural floor plan wireframe alignment snapping neural` ·
`"facade" "diffusion" OR "transformer" generate structured layout "SVG" building elevation drawing` ·
`CMP facade dataset generative layout model rectangles classes learned generation` ·
`building elevation drawing generation deep learning vector CAD architectural facade drawing synthesis` ·
`deformed lattice detection near-regular texture Park Liu facade windows` ·
`LayoutGPT text conditioned layout generation constraints LLM numerical` ·
`"facade layout generation" learned generative model` ·
`text prompt to structured facade layout LLM windows floors generate parametric building` ·
`"split grammar" learning facade generation neural network sample novel facades` ·
`image vectorization repetition aware symmetry aware SVG output regular structure 2025` ·
`"graph-enabled parametric modeling" façade layout generative design` ·
`"Hierarchical attributed graph" generative façade parsing high-rise residential` ·
`Tell2Design text to floorplan generation dataset natural language constraints` ·
`github facade layout generation vector SVG deep learning repository` ·
`regularity constraint loss generative vector output snap to grid alignment neural network` ·
`"facade" generation "vector" OR "SVG" output text description novelty gap 2026 arXiv` ·
`facade image vectorization SVG windows rectangles automatic convert building facade to vector drawing` ·
`learned procedural facade generation text conditioned shape grammar LLM 2026` ·
`"facade" structure generation autoregressive model rectangles floors windows alignment regularity metric evaluation` ·
`facade parsing structured output bounding box dataset benchmark "vector" representation evaluation regularity` ·
`"window" "facade" generative design reinforcement learning rule learned layout not procedural` ·
`generate facade structure from text description vector drawing rectangles semantic classes neural 2026` ·
`"text-guided" OR "text-conditioned" "layout" generation building facade elevation windows doors balconies structured`

</details>

## Прочее найденное, требует проверки

`[всё не проверено]` FaçadeGraph (Automation in Construction 2024) · GEPMA
(Journal of Building Engineering 2025, авторы не установлены) · Controllable
generation of building representations (Frontiers of Architectural Research 2026,
`10.1016/j.foar.2026.01.018`) · DeepFacade (IJCAI 2017) · Building Facade Parsing
R-CNN (arXiv:2205.05912) · Unified Vector Floorplan Generation via Markup
Representation (CVPR 2026, arXiv:2604.04859) · LayoutGPT (NeurIPS 2023) ·
Deformed Lattice Detection (TPAMI 2009) · Deep Vectorization of Technical
Drawings (ECCV 2020) · StarVector, Chat2SVG, OmniSVG, SVGFusion, LLM4SVG.

> Осторожно: arXiv:2303.12755 «Text Semantics to Image Generation» **отозвана
> автором**, ссылаться только на версию Springer `10.1007/978-981-99-8405-3_3`.
