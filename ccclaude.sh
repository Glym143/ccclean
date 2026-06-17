#!/usr/bin/env bash
# ccclaude — обёртка над `claude` с авто-чисткой контекста.
#
# Запускай Claude Code через эту обёртку (в терминале), а не голым `claude`.
# Когда контекст заполняется и срабатывает авто-компакт, хук ccclean-hook.sh
# помечает сессию и завершает claude. Обёртка это ловит, чистит сессию через
# `ccclean` (срезает старые сообщения + правит usage) и перезапускает её.
#
# Базовый размер среза: env CCCLEAN_FREE → config.json "default_free" → 10k.
# Если после чистки сессия СРАЗУ снова за лимитом (цикл, < 90с), режем по
# loop_free (config, по умолч. 10k) — небольшими шагами, пока не выйдем из лимита.
# Метка: хуки авто-чистки (Stop/PreCompact) действуют ТОЛЬКО в сессиях,
# запущенных через эту обёртку — иначе они бы убивали любые сессии Claude Code.
export CCCLEAN_WRAPPED=1
MARKER="$HOME/.claude/ccclean-pending"

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
# Объём при зацикливании (повторная чистка подряд): config "loop_free", по умолч. 10k.
LOOP_FREE="$(cfg_get loop_free 10k)"

rm -f "$MARKER"
ARGS=("$@")
last=0
while true; do
  claude "${ARGS[@]}"
  [ -f "$MARKER" ] || break
  SID="$(cat "$MARKER")"; rm -f "$MARKER"

  now=$(date +%s)
  if [ $((now - last)) -lt 90 ]; then   # снова чистим почти сразу → цикл → режем по loop_free
    FREE="$LOOP_FREE"
  else                                  # первая/одиночная чистка → базовый объём
    FREE="$(base_free)"
  fi
  last=$now

  echo ""
  echo "♻️  Контекст был полон — чищу сессию $SID (срезаю $FREE)…"
  sleep 2   # дать claude полностью закрыться и отпустить файл сессии
  ccclean "$SID" "$FREE" -y --force || { echo "ccclean не смог"; break; }
  echo "↻  Перезапускаю сессию $SID…"
  ARGS=(--resume "$SID")
  [ -n "$RESUME_PROMPT" ] && ARGS+=("$RESUME_PROMPT")   # автоотправка промпта
done
