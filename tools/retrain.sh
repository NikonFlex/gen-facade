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
#   REALTEST_N=0  домов синтетики val в realtest; 0 — все
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

stage_realtest() {
    if [ -z "${MODELS:-}" ]; then
        MODELS="train=$WORK/train/model.pt"
        [ ! -f "$WORK/finetune/model.pt" ] || MODELS="$MODELS finetune=$WORK/finetune/model.pt"
    fi
    set --
    for m in $MODELS; do
        set -- "$@" --model "$m"
    done
    [ ! -d "$WORK/base" ] || set -- "$@" --sheets "base=$WORK/base"
    gf manual
    gf realtest -n "${REALTEST_N:-0}" "$@" -o "$WORK/realtest"
    cat "$WORK/realtest/summary.md"
}

data_config
for stage in "$@"; do
    case $stage in
        base | corpus | train | buildingnet | finetune | realtest)
            echo "== $stage $(date +%T)"
            "stage_$stage"
            ;;
        *)
            echo "нет этапа $stage" >&2
            exit 2
            ;;
    esac
done
