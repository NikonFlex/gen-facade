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

### EvoVec — две работы, разобраны

**PPSN-версия прочитана целиком** — Егор прислал PDF 2026-09-26, лежит в `materials/evovec-ppsn2024.pdf` (вне git). GECCO-версию по-прежнему
не видели: ACM отдаёт 403, открытых копий нет.

**Выходные данные** `[проверено: Crossref API]`:

> Bazhenov E., Jarsky I., Efimova V., Muravyov S. EvoVec: Evolutionary Image
> Vectorization with Adaptive Curve Number and Color Gradients // Parallel Problem
> Solving from Nature – PPSN XVIII. Lecture Notes in Computer Science.
> Cham: Springer, 2024. **P. 383–397**. DOI: 10.1007/978-3-031-70085-9_24.

> Bazhenov E., Jarsky I., Efimova V., Muravyov S. Evolutionary image vectorization
> with variable curve number // GECCO '24 Companion. Melbourne VIC, Australia.
> New York: ACM, 2024. **P. 2083–2086**. DOI: 10.1145/3638530.3664171.

Разница между ними: GECCO — **4 страницы в секции Student Workshop**
`[из отчёта агента, по OpenTOC SIGEVO]`, PPSN — полноформатная статья на 15 страниц.
PPSN добавляет 8 источников (Im2Vec, VectorFusion, эволюционная векторная графика,
цветовые градиенты) — то есть это расширенная версия с градиентной заливкой
и нормальным related work. Заявление про +15% MSE в обоих абстрактах одинаковое.

**Дословный абстракт GECCO-версии** `[проверено: OpenTOC SIGEVO + OpenAlex, совпадают]`
перечисляет ровно четыре свойства метода: работа с цветовым градиентом, отсутствие
артефактов, точность по MSE, скорость. Плюс «does not generate unnecessary shapes» —
это про **количество** путей, не про геометрию.

### С чем сравнивались `[проверено: полный текст, materials/evovec-ppsn2024.pdf]`

> ⚠ **Исправление.** Раньше здесь было записано, что «+15% по MSE» — это среднее
> по восьми клипарт-картинкам из `data/test images`. **Это неверно.** Вывод был
> сделан по содержимому репозитория, до получения полного текста. Ниже — как на
> самом деле, по статье.

Сравнений в статье два, и их нельзя смешивать:

**Таблица 1 — качественная, 5 изображений.** Бейзлайны LIVE, DiffVG, Pixels2Svg,
SvgTracer; метрики — время, fitness, число путей. Для LIVE задано `N = 16`,
для DiffVG `N = 512` (у них число путей — обязательный параметр, у EvoVec нет).

**Таблица 2 — количественная, 400 изображений:** по 100 картинок на каждое из
четырёх разрешений 128×128, 256×256, 512×512, 1024×1024. Но сравнение там
**только с детерминированными алгоритмами** — Pixels2Svg и SvgTracer, без
LIVE и DiffVG.

Выигрыш по fitness относительно SvgTracer: −16.9% (128px), −13.8% (256px),
−12.1% (512px), **−6.8% (1024px)**. Относительно Pixels2Svg: −69.6%, −27.9%,
−18.8%, −9.6%.

**Существенное для нас: преимущество падает с ростом разрешения** — с 16.9%
до 6.8%. Заявленные в абстракте «15%» соответствуют сравнению с детерминированными
алгоритмами на малых разрешениях; в тексте эта цифра к конкретной таблице
явно не привязана.

Железо: **CPU, 16 ГБ RAM, 10 ядер, GPU не использовались.**
Гиперпараметры: популяция 30, элита 10%, 300 итераций.

Измерение агента по сохранённым в репозитории SVG `[не проверено лично]`:
EvoVec выдаёт **сотни и тысячи путей** (от 7 до 2947 на картинку) и никогда
не превышает число путей своей инициализации, а на трёх картинках из восьми
не сокращает его вовсе. У LIVE для тех же картинок — 5–35 путей.
**Для чертежа фасада, где число примитивов должно соответствовать числу
архитектурных элементов, это плохая новость.**

### Future work — проверено по первоисточнику

Раздел Conclusion, страница 14. Авторы называют три направления:

1. новые типы мутаций и кроссоверов — против долгого времени работы и ради точности;
2. альтернативные функции отбора — ради скорости;
3. **работать напрямую с контурами векторного изображения**, чтобы считать качество
   без избыточной растеризации.

**Структурных и геометрических ограничений среди планов нет.** Идея свободна —
теперь это подтверждено первоисточником, а не косвенными признаками.

Честная оговорка: пункт 1 сформулирован широко, и оператор привязки координат
к сетке формально под него подпадает. Но как направление это не заявлено.

### Расхождения статьи и кода `[проверено: статья + код]`

Важно, если строить на EvoVec:

| В статье | В коде |
|---|---|
| кроссовер описан (обмен случайными путями) и вынесен в абстракт | `CROSSOVER = []` — **в дефолтном конфиге выключен** |
| четыре мутации, включая удаление сегмента | `DropSegment` удаляет **путь** по индексу сегмента — баг, и по умолчанию не включена |
| needle-мутация «ограничена размером изображения» | в коде `(value + sign*ratio) % 1`, а координаты в пикселях — схлопывает в [0,1) |
| три функции отбора (L1, экспоненциальная, квадратичная) | четыре: добавлен `OPT_TRANSPORT` |

Ablation из таблицы 3 (изображение «лист», fitness / число путей):
все мутации 628 / 793; без needle 736 / 793; без удаления 796 / **2187**;
без градиентной 698 / 793.

### Канонический репозиторий — личный, не VGLib

В статье указан **github.com/EgorBa/EvoVec-Evolutionary-Image-Vectorization**
(12 звёзд, обновлён 2026-05-28), а копия в VGLib не обновлялась с 2024-12-26.
**Лицензии нет и там** `[проверено: GitHub API]` — то есть gf#20 не снимается.

Финансирование подтверждено дословно: «supported by the ITMO University,
project 623097 "Development of libraries containing perspective machine
learning methods"».

### Ответ на главный вопрос: структурных ограничений в EvoVec нет

Идея студента статьёй **не занята**. Четыре независимых основания:

1. **Абстракты** — ни одного геометрического или структурного термина.
2. **Fitness** — все четыре варианта попиксельные или цветовые `[проверено: код]`.
3. **Операторы структуру разрушают** — `Needle` двигает одну координату из шести
   независимо, `ConcatPath` сливает соседние по цвету пути `[проверено: код]`.
4. **Списки литературы** (19 и 12 источников, `[из отчёта агента, по OpenAlex]`) —
   **ни одной** работы про shape grammars, регулярные решётки, детекцию
   повторяемости, structure-aware векторизацию, CAD-констрейнты, фасады
   или архитектуру. Только классика ЭА, растеризация и векторизация.

Формулировка, которую можно защищать:

> В EvoVec функция приспособленности целиком попиксельная; структурные
> и геометрические ограничения — выравнивание, повторяемость, регулярность —
> ни в постановке задачи, ни в функции приспособленности, ни в операторах
> не заявлены. Единственное структурное по духу свойство метода — сокращение
> числа путей относительно детерминированной инициализации, что относится
> к сложности представления, а не к геометрии.

**Оговорка:** это опирается на абстракты, код и списки литературы, но не на текст
15-страничной PPSN-версии. Перед защитой текст надо достать и убедиться, что идея
не заявлена в разделе future work. Риск небольшой, закрывается одним сообщением Егору.

### «Adaptive curve number» — что это на самом деле

Не адаптивное наращивание, а **монотонное сокращение** `[проверено: код]`.
Старт — переусложнённая детерминированная трассировка, дальше `ConcatPath` сливает,
`DropPath` удаляет мелкие, ни один оператор путь не добавляет. Штрафа за число
кривых в fitness нет — сокращение получается из устройства операторов.

Ещё деталь: в дефолтном конфиге **кроссовер выключен** (`CROSSOVER = []`),
хотя в абстракте заявлены «mutations and crossovers".

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
Статус: **прочитано**. Полный конспект ниже, в разделе «Две ключевые работы».

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

### Generative artificial intelligence in building facade design
Aghimien, Akšamija · `10.1016/j.buildenv.2026.115041`
Статус: **абстракт прочитан дословно**, тело недоступно. Конспект ниже.

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

---

# Две ключевые работы — прочитаны

## Pro-DG: Procedural Diffusion Guidance for Architectural Facade Generation

Plocharski (Warsaw UT), Swidzinski (Imperial College London), Musialski (NJIT) ·
*Computer Graphics Forum* 2026, `10.1111/cgf.70487` · arXiv:2504.01571v2, CC BY 4.0
Статус: **прочитано** (полный текст arXiv HTML), ключевое `[проверено: grep по полному тексту]`.

**Это та же группа, что сделала FaçAID.** Pro-DG — прямое продолжение FaçAID,
и продолжение ушло **в растр, а не в вектор**. Для нас это важнее самого метода.

**Задача — редактирование существующего фото фасада, а не генерация.**
Вход: фото + семантическая сегментация + **вручную отредактированное пользователем
процедурное дерево**. Выход: растровое фото (SD 1.5).

Пайплайн: инверсная процедурная реконструкция (используют **FaçAID как чёрный ящик**)
→ правка структуры пользователем → иерархическое сопоставление символов →
Null-text Inversion → guided inference. Control signal — новая карта Canny
в ControlNet плюс перенесённые активации сети.

Грамматика **заданная заранее**, выучен только вывод дерева по картинке.

Данные: ControlNet дообучен на 23k изображений из LSAA. **CMP не использовался**
`[проверено: grep, ноль совпадений по CMP/eTRIMS/Graz]`.
Метрики: user study (105 участников), Sliced Wasserstein Distance, CLIP Cosine Distance.

**Векторного выхода нет** `[проверено: grep по svg/vector — ноль совпадений]`.
Процедурное дерево — промежуточное представление, оно управляет диффузией
и выбрасывается.

**Их собственные limitations, полезные нам:**

- *«The main failure mode occurs when the grammar on which the model was trained
  cannot express the structure of a given facade»* `[проверено: дословно в тексте]` —
  жёсткая рукописная грамматика не выражает нестандартные раскладки
- метод **не умеет добавлять элементы, которых не было в оригинале** — сопоставлять
  не с чем. То есть генерировать новое он в принципе не может, только переставлять
- ошибки FaçAID накапливаются и распространяются по пайплайну
- SD 1.5 как бэкбон ограничивает реализм

Кода публично нет (обещан «on the project's website», репозиторий не найден
на 25.09.2026).

## Aghimien, Akšamija. Generative AI in Building Facade Design

*Building and Environment*, Vol. 304 Part A, art. 115041, 2026 ·
`10.1016/j.buildenv.2026.115041` · Review article, Open Access CC BY 4.0
Статус: **абстракт прочитан дословно**, тело статьи недоступно (ScienceDirect
отдаёт captcha). Абстракт `[проверено: реконструирован из OpenAlex API,
совпадает со страницей ScienceDirect и страницами University of Utah]`.

Метод: content analysis и критический обзор по четырём осям — категории моделей,
типы данных, стратегии оценки, прикладные домены.

**Две цитаты, которые работают на нашу новизну:**

> «Also, **image-based data type dominates both model input and output**, while
> visual assessment and Structural Similarity Index (SSIM) are the most frequently
> used evaluation methods.»

> «the study identified several key research gaps, including ... the development of
> **architecture-specific** generative AI tools, the **limited adoption of
> geometry-aware** and immersive workflows ...»

Прочее из абстракта: GAN остаются самыми используемыми моделями; выделено семь
прикладных доменов; среди пробелов также недоисследованность autoencoder, NeRF
и Gaussian Splatting.

> Внимание к фамилии в списке литературы: **Akšamija**, с диакритикой.

---

# Чем это обосновывается, а чем нет

## Работает на новизну

**Пробел «выход растровый, а не векторный».** Цитата из свежего рецензируемого
обзора: image-based доминирует и на входе, и на выходе. Это говорим не мы,
а профильный журнал. Pro-DG — идеальная иллюстрация на переднем крае: метод
**явно строит** символическую иерархию фасада, но финальный артефакт всё равно
растр, а структура выбрасывается. **Наш ход — сделать структуру выходом,
а не внутренним управляющим сигналом.**

**Пробел «управление не текстом».** Дословно из Pro-DG
`[проверено: дословно в тексте]`:

> «Our method employs procedural-level control—leveraging a domain-specific grammar
> to define facade layouts with precision, **rather than relying on purely
> pixel-based or language-based constraints**.»

Авторы **сознательно отказываются** от языкового управления в пользу ручного
редактирования дерева грамматики. Это их собственная позиционная фраза,
и она прямо оставляет нишу «текстовое описание → структура фасада» свободной.
Плюс механика: они используют **Null-text Inversion**, то есть текстовый канал
диффузии у них буквально занулён.

**Рукописная грамматика как ограничение.** Их limitation про невыразимость
нестандартных раскладок — аргумент в пользу выученной из данных структуры.

**Метрики как вклад, а не рутина.** Обзор фиксирует, что область меряет
качество **глазами и SSIM**. Pro-DG изнутри CG подтверждает: user study,
SWD, CLIP — всё перцептивное, метрики структурной корректности выхода нет.
Значит проверяемые метрики геометрической регулярности — это вклад.

Отдельно полезно: **SVD-метрика структурного сходства** из Pro-DG (раздел 3.2,
псевдокод в приложении A) — считает «структурную сложность» региона через
ранг матрицы. Как метрику оценки они её не используют, но идею можно
переиспользовать для нашей метрики регулярности.

## Чего этим обосновать НЕЛЬЗЯ

Чтобы не подставиться на защите:

- **Нельзя** сказать «обзор констатирует отсутствие работ с векторным выходом» —
  в абстракте такого утверждения нет, тело статьи не читано. Корректно:
  «в сводных выводах обзора векторное представление не фигурирует, а главный
  вывод о данных — доминирование растра на входе и на выходе».
- **Нельзя** сказать «Pro-DG не использует текст вообще» — текстовый канал есть,
  но занулён. Корректно: «текстом структура не управляется».
- **Нельзя** сказать «Pro-DG обучен на CMP» — он на CMP не обучался.
- Для цитаты из обзора с номером страницы нужен доступ через ИТМО. Статья
  Open Access, вопрос не в правах, а в captcha.

---

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

---

# Фасады по плану: поиск 2026-09-28 (gf#37)

Искали работы «план / контур → фасады или экстерьер», «план + текст → дом»,
векторные фасады. Поиск делал агент, ключевое перепроверено лично.

**Ближайшие — назвать в обзоре обязательно:**

- **ShellMaker: Language-Guided Exterior Completion under Structural Constraints** ·
  Xu, Aliaga · **ECCV 2026** · arXiv:2606.31680 · https://ruiqixu37.github.io/ShellMaker_web/
  `[проверено: страница arXiv + HTML-версия]`. Вход — каркас здания (контур, стены,
  **заданные** проёмы) + текст стиля; выход — 3D-меш с PBR-материалами
  и параметрической крышей. Проёмы не генерирует. Ограничение из §4.7 дословно:
  «treats the facade as a single massing shell and stylizes openings uniformly
  without modeling per-floor articulation». Код обещан («All code and data will
  be released»). Мотивация совпадает с нашей: «Existing methods can generate floor
  plans and wall layouts but typically stop at a structural shell».
- **ArchyBase, Floor Plan to Elevation AI** — коммерческий сервис,
  https://www.archybase.com/floor-plan-to-elevation `[проверено: страница]`.
  План (картинка, PDF, DXF) → фасады front / rear / left / right, экспорт
  PDF, PNG, **SVG, DXF**; «infers wall heights, roof pitch, window sizes, and door
  positions». Текст — необязательное поле. Метода и статьи нет.
  **Из-за него нельзя заявлять «первыми генерируем фасады по плану».**
- **GeoTexBuild: 3D Building Model Generation from Map Footprints** · Wang, Yang, Wang ·
  arXiv:2504.08419 `[проверено: страница arXiv]`. Контур → карта высот → геометрия →
  стиль (ControlNet, NSF, multi-view diffusion) → 3D. Проёмов на входе нет.
- **Text2BIM** · Du, Esser, Nousias, Borrmann · J. Computing in Civil Engineering ·
  arXiv:2408.08054 `[проверено: страница arXiv + HTML v1]`. Текст → BIM через
  LLM-агентов, плана на входе нет. Подпись к рис. 12 дословно: «the reasonable
  arrangement of building openings, a task requiring advanced spatial
  understanding, poses a challenge for all LLMs» — аргумент для режима,
  где модуль ставит проёмы сам.

**ProxyBuild** (Tang, Li, Fan, arXiv:2609.23386, 20.09.2026) — текст →
структурированное редактируемое 3D-здание `[проверено: аннотация]`; ставит ли
модель окна сама, по аннотации не видно — агент утверждал, что да, не подтверждено.

**Из отчёта агента, лично не открывал** `[не проверено]`: BuildingBlock (SIGGRAPH 2025, arXiv:2505.04051),
CityGenAgent (arXiv:2602.05362), Retrieval-Augmented Sketch-Guided 3D Building
Generation (arXiv:2603.16612), Multi-View Depth Consistent Image Generation
(CAADRIA 2025, arXiv:2503.03068), Daylight-driven Architectural Design
(CVPR 2024 W, arXiv:2404.13353), HouseCrafter (ICCV 2025) и Plan2Scene
(CVPR 2021) — интерьеры, Building-GAN (ICCV 2021), Sketch2BIM (arXiv:2510.20838),
две работы по сельским фасадам Чжэцзяна (FoAR 2025, Buildings 2026).

**Искали и не нашли** (arXiv API по аннотациям): `facade AND floorplan` — 0;
`facade AND SVG` — 0; `facade AND vector AND generation` — 0; `"elevation drawing"` —
0 релевантных. Русскоязычный поиск («генерация фасада по плану нейросеть»,
cyberleninka) — только коммерческие сервисы рестайлинга по фото и проекции
готовой 3D-модели в Revit/Renga.

**Вывод:** открытого воспроизводимого метода «векторный план + текст → четыре
согласованных векторных фасада» не найдено. Новизна — в сочетании, см. `docs/plan.md`, раздел 3.
