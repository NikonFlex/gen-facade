#!/bin/sh
# Переобучение модели шага 4 и сравнение с прежней на реальном тесте (gf#212) — этапами.
# Одни и те же команды идут в .github/workflows/gpu.yml (job retrain, а также train, finetune,
# realtest) и в локальном прогоне в миниатюре: машины отличаются только папками и числами.
#
#   sh tools/retrain.sh <этап>...
#
# Этапы, по порядку цепочки retrain:
#   base         прежняя модель (BASE_MODEL) на своём коде (BASE_CODE): realtest → $WORK/base;
#                её листы потом — строкой сводной таблицы (модель другой записи токенов
#                отвечает только на своём коде); идёт первым — отказ виден до обучения
#   corpus       синтетика (HOUSES домов, REBUILD=true — заново) и корпус токенов
#   train        новая модель → $WORK/train
#   buildingnet  коттеджи BuildingNet (BUILDINGNET — папка tools/fetch_buildingnet.py) и корпусы
#   finetune     дообучение INIT на BuildingNet → $WORK/finetune
#   mixfit       обучение с нуля, без INIT, на BuildingNet train с подмешанными MIX
#                последовательностями синтетики → $WORK/mixfit (gf#217: «смесью»; после
#                corpus и buildingnet, этапа train не нужно)
#   realtest     таблица против реального теста: строки MODELS и листы $WORK/base → $WORK/realtest,
#                сводка — $WORK/realtest/summary.md
#
# Переменные (обязательны WORK и SAMPLES; пути — без пробелов):
#   WORK          папка запуска: настройки этапов, модели, таблицы
#   SAMPLES       папка домов и корпусов (samples_dir); на GPU-машине переживает запуски
#   CONFIG        своя папка настроек поверх умолчаний (локально — крошечная модель)
#   HOUSES=10000 EPOCHS=10 REBUILD=false
#   PLACEMENT     rules | random — расстановка проёмов синтетики (config/synthetic.toml,
#                 [openings] placement, gf#217). Не задан — как в настройках. random — свои дома
#                 и корпус в $SAMPLES/random (собранные rules не затираются), BuildingNet — общий,
#                 по ссылке из $SAMPLES/buildingnet
#   BUILDINGNET   BN_COUNT=0 (коттеджей; 0 — все)
#   INIT=$WORK/train/model.pt FT_EPOCHS=3 LR=1e-4
#   MIX=1500      сколько последовательностей train синтетики подмешать к BuildingNet в finetune
#                 и mixfit; 0 — без примеси (в finetune: чисто последовательно)
#   MIX_EPOCHS=100 PROBE_EVERY=5     mixfit: эпох; датчик раз в столько эпох
#   BASE_MODEL BASE_CODE BASE_HOUSES=100 (синтетики для строки generator прежнего кода)
#   MODELS        «имя=чекпойнт …» — строки model-<имя>; по умолчанию — модели этапов обучения
#                 в $WORK: model-train, model-finetune, model-mixfit — какие были
#   REALTEST_N=0  домов синтетики val в realtest; 0 — все
#
# В миниатюре (без GPU; BuildingNet и PDF реальных домов — в data/ этого репо). Крошечная модель и
# одна попытка на дом через CONFIG; корпус и обучение — минуты, realtest на процессоре — около
# получаса (FID и KID по растрам), окно модели растёт до самой длинной последовательности:
#   export WORK=/tmp/mini SAMPLES=/tmp/mini-samples CONFIG=/tmp/mini-config
#   mkdir -p $CONFIG && printf '[layout]\nattempts = 1\n' > $CONFIG/models.toml
#   printf '[model]\nblock = 256\nlayers = 1\nheads = 2\nwidth = 32\n\n[fit]\nbatch = 8\nsave_every = 0\n\n[probe]\nevery = 0\n\n[sample]\ncount = 4\n' > $CONFIG/train.toml
#   PLACEMENT=random HOUSES=30 EPOCHS=1 REALTEST_N=4 sh tools/retrain.sh corpus train realtest
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
: "${WORK:?папка запуска}" "${SAMPLES:?папка домов}"
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)

# genfacade из папки кода: из рабочей копии берётся её пакет, а не установленный в venv
# (в worktree и для прежнего кода в BASE_CODE).
code_gf() {
    dir=$1
    shift
    (cd "$dir" && python -c 'from genfacade.cli import main; main()' "$@")
}

# genfacade этого кода: умолчания, поверх — CONFIG, папка данных запуска, расстановка проёмов.
gf() {
    code_gf "$root" ${CONFIG:+-c "$CONFIG"} -c "$WORK/config/data" \
        ${PLACEMENT:+-c "$WORK/config/placement"} "$@"
}

# Папка настроек этапа: файл <имя> с текстом из stdin.
stage_config() {
    mkdir -p "$WORK/config/$1"
    cat > "$WORK/config/$1/$2"
    echo "$WORK/config/$1"
}

# Расстановка проёмов синтетики — слоем настроек поверх CONFIG и папки данных. random — свои дома и
# корпус: $SAMPLES переживает запуски, и собранная синтетика rules в нём не затирается; BuildingNet
# от расстановки не зависит и остаётся общим — ссылкой на папку $SAMPLES/buildingnet.
placement_config() {
    case ${PLACEMENT:-} in
        "") return 0 ;;
        rules | random) ;;
        *) echo "PLACEMENT: rules или random, а не $PLACEMENT" >&2; exit 2 ;;
    esac
    printf '[openings]\nplacement = "%s"\n' "$PLACEMENT" \
        | stage_config placement synthetic.toml > /dev/null
    [ "$PLACEMENT" = random ] || return 0
    mkdir -p "$SAMPLES/buildingnet" "$SAMPLES/random"
    [ -e "$SAMPLES/random/buildingnet" ] || ln -s ../buildingnet "$SAMPLES/random/buildingnet"
    SAMPLES=$SAMPLES/random
}

data_config() {
    mkdir -p "$WORK/config/data"
    printf '[paths]\nsamples_dir = "%s"\n' "$SAMPLES" > "$WORK/config/data/data.toml"
    [ -n "${BUILDINGNET:-}" ] || return 0
    printf '\n[buildingnet.paths]\nmodels_dir = "%s"\ncomponent_labels = "%s"\n' \
        "$BUILDINGNET/v1/OBJ_MODELS" "$BUILDINGNET/probe/v1/component_labels.zip" \
        >> "$WORK/config/data/data.toml"
    printf '\n[buildingnet.paths.splits]\ntrain = "%s"\nval = "%s"\ntest = "%s"\n' \
        "$BUILDINGNET/probe/v1/train_split.txt" "$BUILDINGNET/probe/v1/val_split.txt" \
        "$BUILDINGNET/probe/v1/test_split.txt" >> "$WORK/config/data/data.toml"
}

stage_base() {
    : "${BASE_MODEL:?чекпойнт прежней модели}" "${BASE_CODE:?папка её кода}"
    model=$(cd "$(dirname "$BASE_MODEL")" && pwd)/$(basename "$BASE_MODEL")
    cfg=$(printf '[layout]\ncheckpoint = "%s"\n' "$model" | stage_config base models.toml)
    printf '[paths]\nsamples_dir = "%s"\n' "$WORK/base-samples" > "$cfg/data.toml"
    # Свои дома: прежний код может не прочесть записанные новым.
    code_gf "$BASE_CODE" -c "$cfg" manual
    code_gf "$BASE_CODE" -c "$cfg" synth -n "${BASE_HOUSES:-100}"
    code_gf "$BASE_CODE" -c "$cfg" realtest -o "$WORK/base"
}

stage_corpus() {
    overwrite=""
    case "${REBUILD:-false}" in true | 1) overwrite=--overwrite ;; esac
    gf synth -n "${HOUSES:-10000}" $overwrite
    gf tokens
    head -30 "$SAMPLES/synthetic/_tokens.json"
}

stage_train() {
    cfg=$(printf '[fit]\nepochs = %s\n' "${EPOCHS:-10}" | stage_config train train.toml)
    gf -c "$cfg" train -o "$WORK/train"
}

stage_buildingnet() {
    : "${BUILDINGNET:?папка BuildingNet}"
    gf buildingnet --splits train val test -n "${BN_COUNT:-0}"
    gf tokens -s buildingnet
    gf tokens    # синтетика для примеси [fit.mix] — тем же кодом, что BuildingNet
    head -40 "$SAMPLES/buildingnet/_manifest.json"
    head -20 "$SAMPLES/buildingnet/_tokens.json"
}

# Примесь синтетики к источнику обучения: таблица [fit.mix]; MIX=0 — без неё (пустая таблица —
# настройка по умолчанию).
mix_config() {
    [ "${MIX:-1500}" -eq 0 ] || printf '\n[fit.mix]\nsynthetic = %s\n' "${MIX:-1500}"
}

stage_finetune() {
    init=${INIT:-$WORK/train/model.pt}
    init=$(cd "$(dirname "$init")" && pwd)/$(basename "$init")
    cfg=$({
        printf '[fit]\nepochs = %s\nlr = %s\nwarmup_steps = 50\nsave_every = 1\ninit = "%s"\nskip_longer = true\n' \
            "${FT_EPOCHS:-3}" "${LR:-1e-4}" "$init"
        mix_config
        printf '\n[probe]\nevery = 1\n'
    } | stage_config finetune train.toml)
    gf -c "$cfg" train -s buildingnet -o "$WORK/finetune"
}

# С нуля, без INIT: корпус — BuildingNet train и MIX последовательностей train синтетики; val и
# датчик — BuildingNet (fit.mixed). Окно новой модели — по самой длинной последовательности смеси.
stage_mixfit() {
    cfg=$({
        printf '[fit]\nepochs = %s\nsave_every = 0\n' "${MIX_EPOCHS:-100}"
        mix_config
        printf '\n[probe]\nevery = %s\n' "${PROBE_EVERY:-5}"
    } | stage_config mixfit train.toml)
    gf -c "$cfg" train -s buildingnet -o "$WORK/mixfit"
}

stage_realtest() {
    if [ -z "${MODELS:-}" ]; then
        for name in train finetune mixfit; do
            [ ! -f "$WORK/$name/model.pt" ] || MODELS="${MODELS:+$MODELS }$name=$WORK/$name/model.pt"
        done
    fi
    : "${MODELS:?нет моделей для реального теста: ни одного model.pt в $WORK}"
    set --
    for m in $MODELS; do
        set -- "$@" --model "$m"
    done
    [ ! -d "$WORK/base" ] || set -- "$@" --sheets "base=$WORK/base"
    gf manual
    gf realtest -n "${REALTEST_N:-0}" "$@" -o "$WORK/realtest"
    cat "$WORK/realtest/summary.md"
}

placement_config
data_config
for stage in "$@"; do
    case $stage in
        base | corpus | train | buildingnet | finetune | mixfit | realtest)
            echo "== $stage $(date +%T)"
            "stage_$stage"
            ;;
        *)
            echo "нет этапа $stage" >&2
            exit 2
            ;;
    esac
done
