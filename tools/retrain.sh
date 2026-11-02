#!/bin/sh
# Переобучение модели шага 4 и сравнение с прежней на реальном тесте (gf#212) — этапами.
# Одни и те же команды идут в .github/workflows/gpu.yml (job retrain, а также train, finetune,
# realtest, stability) и в локальном прогоне в миниатюре: машины отличаются только папками и числами.
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
#   realtest     таблица против реального теста: строки MODELS и листы $WORK/base → $WORK/realtest,
#                сводка — $WORK/realtest/summary.md
#
# Переменные (обязательны WORK и SAMPLES; пути — без пробелов):
#   WORK          папка запуска: настройки этапов, модели, таблицы
#   SAMPLES       папка домов и корпусов (samples_dir); на GPU-машине переживает запуски
#   CONFIG        своя папка настроек поверх умолчаний (локально — крошечная модель)
#   HOUSES=10000 EPOCHS=10 REBUILD=false
#   BUILDINGNET   BN_COUNT=0 (коттеджей; 0 — все)
#   INIT=$WORK/train/model.pt FT_EPOCHS=3 LR=1e-4 MIX=1500
#   BASE_MODEL BASE_CODE BASE_HOUSES=100 (синтетики для строки generator прежнего кода)
#   MODELS        «имя=чекпойнт …» — строки model-<имя>; по умолчанию — модели этапов обучения
#                 в $WORK: model-train и, если было дообучение, model-finetune
#   REALTEST_N=0  домов синтетики val в realtest и stability; 0 — все
#   VARIANTS      варианты сэмплинга для stability через «;»; вариант — пары ключ=значение
#                 настроек [layout] (config/models.toml) через пробел, число или true/false:
#                 "seed=0;seed=1;temperature=0.8 seed=0;top_k=20 seed=0;best_of=4 seed=0";
#                 папка варианта — пары через запятую: temperature=0.8,seed=0
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

# genfacade этого кода: умолчания, поверх — CONFIG, поверх — папка данных запуска.
gf() {
    code_gf "$root" ${CONFIG:+-c "$CONFIG"} -c "$WORK/config/data" "$@"
}

# Папка настроек этапа: файл <имя> с текстом из stdin.
stage_config() {
    mkdir -p "$WORK/config/$1"
    cat > "$WORK/config/$1/$2"
    echo "$WORK/config/$1"
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

stage_finetune() {
    init=${INIT:-$WORK/train/model.pt}
    init=$(cd "$(dirname "$init")" && pwd)/$(basename "$init")
    cfg=$(printf '[fit]\nepochs = %s\nlr = %s\nwarmup_steps = 50\nsave_every = 1\ninit = "%s"\nskip_longer = true\n\n[fit.mix]\nsynthetic = %s\n\n[probe]\nevery = 1\n' \
        "${FT_EPOCHS:-3}" "${LR:-1e-4}" "$init" "${MIX:-1500}" | stage_config finetune train.toml)
    gf -c "$cfg" train -s buildingnet -o "$WORK/finetune"
}

# Строки моделей для `gf realtest`: --model на каждую из MODELS, без них — на модели этапов
# обучения в $WORK (пути без пробелов, как и везде здесь).
model_args() {
    models=${MODELS:-}
    if [ -z "$models" ]; then
        models="train=$WORK/train/model.pt"
        [ ! -f "$WORK/finetune/model.pt" ] || models="$models finetune=$WORK/finetune/model.pt"
    fi
    for m in $models; do
        printf -- '--model %s ' "$m"
    done
}

stage_realtest() {
    sheets=""
    [ ! -d "$WORK/base" ] || sheets="--sheets base=$WORK/base"
    gf manual
    gf realtest -n "${REALTEST_N:-0}" $(model_args) $sheets -o "$WORK/realtest"
    cat "$WORK/realtest/summary.md"
}

# Один вариант сэмплинга (пары ключ=значение через пробел): свой слой настроек [layout] поверх
# CONFIG и реальный тест в $WORK/stability/<пары через запятую>.
stability_variant() {
    set -- $1
    [ $# -gt 0 ] || return 0
    name=$(printf '%s' "$*" | tr ' ' ',')
    echo "== вариант $name $(date +%T)"
    cfg=$({
        echo '[layout]'
        for pair in "$@"; do
            printf '%s = %s\n' "${pair%%=*}" "${pair#*=}"
        done
    } | stage_config "stability-$name" models.toml)
    gf -c "$cfg" realtest -n "${REALTEST_N:-0}" $(model_args) -o "$WORK/stability/$name" < /dev/null
}

stage_stability() {
    : "${VARIANTS:?варианты через «;»}"
    gf manual
    printf '%s\n' "$VARIANTS" | tr ';' '\n' | while read -r variant; do
        stability_variant "$variant"
    done
    gf stability "$WORK/stability"
    cat "$WORK/stability/summary.md"
}

data_config
for stage in "$@"; do
    case $stage in
        base | corpus | train | buildingnet | finetune | realtest | stability)
            echo "== $stage $(date +%T)"
            "stage_$stage"
            ;;
        *)
            echo "нет этапа $stage" >&2
            exit 2
            ;;
    esac
done
