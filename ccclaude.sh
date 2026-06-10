#!/usr/bin/env bash
# ccclaude — обёртка над `claude` с авто-чисткой контекста.
#
# Запускай Claude Code через эту обёртку (в терминале), а не голым `claude`.
# Когда контекст заполняется и срабатывает авто-компакт, хук ccclean-hook.sh
# помечает сессию и завершает claude. Обёртка это ловит, чистит сессию через
# `ccclean` (срезает старые сообщения + правит usage) и перезапускает её.
#
# Базовый размер среза: env CCCLEAN_FREE → config.json "default_free" → 10k.
# Если после чистки сессия СРАЗУ снова за лимитом (цикл), срез эскалируется
# по лестнице, чтобы выйти из лимита за 2-3 круга, а не за десяток.
# Метка: хуки авто-чистки (Stop/PreCompact) действуют ТОЛЬКО в сессиях,
# запущенных через эту обёртку — иначе они бы убивали любые сессии Claude Code.
export CCCLEAN_WRAPPED=1
MARKER="$HOME/.claude/ccclean-pending"
EFFORT_FILE="$HOME/.claude/ccclean-effort"   # уровень рассуждений, сохранённый хуком

# значение из config.json по ключу (с дефолтом)
cfg_get() {  # $1=ключ, $2=дефолт
  local v
  v=$(python3 -c "import json,os
try:
    print(json.load(open(os.path.expanduser('~/.config/ccclean/config.json'))).get('$1') or '')
except Exception:
    print('')" 2>/dev/null)
  echo "${v:-$2}"
}

# базовый объём среза
base_free() {
  [ -n "${CCCLEAN_FREE:-}" ] && { echo "$CCCLEAN_FREE"; return; }
  cfg_get default_free 10k
}

# Промпт, который автоматически отправляется после перезапуска (config.json
# "resume_prompt", по умолч. "continue"). Пусто → просто резюм без отправки.
RESUME_PROMPT="$(cfg_get resume_prompt continue)"

rm -f "$MARKER"
ARGS=("$@")
LADDER=(50k 150k 400k 800k)   # эскалация при зацикливании
step=0
last=0
while true; do
  claude "${ARGS[@]}"
  [ -f "$MARKER" ] || break
  SID="$(cat "$MARKER")"; rm -f "$MARKER"

  now=$(date +%s)
  if [ $((now - last)) -lt 90 ]; then   # снова чистим почти сразу → цикл → эскалируем
    FREE="${LADDER[$step]:-${LADDER[${#LADDER[@]}-1]}}"
    [ $step -lt $((${#LADDER[@]}-1)) ] && step=$((step+1))
  else                                  # нормальный одиночный случай → базовый объём
    FREE="$(base_free)"; step=0
  fi
  last=$now

  echo ""
  echo "♻️  Контекст был полон — чищу сессию $SID (срезаю $FREE)…"
  sleep 2   # дать claude полностью закрыться и отпустить файл сессии
  ccclean "$SID" "$FREE" -y --no-summary --force || { echo "ccclean не смог"; break; }
  echo "↻  Перезапускаю сессию $SID…"
  ARGS=(--resume "$SID")
  # восстановить уровень рассуждений, если хук его сохранил
  if [ -f "$EFFORT_FILE" ]; then
    EFF="$(cat "$EFFORT_FILE")"; rm -f "$EFFORT_FILE"
    [ -n "$EFF" ] && ARGS+=(--effort "$EFF")
  fi
  [ -n "$RESUME_PROMPT" ] && ARGS+=("$RESUME_PROMPT")   # автоотправка промпта
done
