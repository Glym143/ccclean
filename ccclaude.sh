#!/usr/bin/env bash
# ccclaude — обёртка над `claude` с авто-чисткой контекста.
#
# Запускай Claude Code через эту обёртку (в терминале), а не голым `claude`.
# Когда контекст заполняется и срабатывает авто-компакт, хук ccclean-hook.sh
# помечает сессию и завершает claude. Обёртка это ловит, чистит сессию через
# `ccclean` (срезает старые сообщения + правит usage) и перезапускает её.
#
# Размер среза за один раз задаётся переменной CCCLEAN_FREE (по умолчанию 10k):
#   CCCLEAN_FREE=300k ccclaude --resume <session-id>
MARKER="$HOME/.claude/ccclean-pending"
# Сколько срезать за один раз. Приоритет: env CCCLEAN_FREE → config.json
# ("default_free") → 10k. Так значение легко поменять в конфиге раз и навсегда.
FREE="${CCCLEAN_FREE:-}"
if [ -z "$FREE" ]; then
  FREE=$(python3 -c 'import json,os
try:
    v=json.load(open(os.path.expanduser("~/.config/ccclean/config.json"))).get("default_free")
    print(v or "")
except Exception:
    print("")' 2>/dev/null)
fi
FREE="${FREE:-10k}"
rm -f "$MARKER"
ARGS=("$@")
while true; do
  claude "${ARGS[@]}"
  if [ -f "$MARKER" ]; then
    SID="$(cat "$MARKER")"; rm -f "$MARKER"
    echo ""
    echo "♻️  Контекст был полон — чищу сессию $SID (срезаю $FREE)…"
    sleep 2   # дать claude полностью закрыться и отпустить файл сессии
    ccclean "$SID" "$FREE" -y --no-summary --force || { echo "ccclean не смог"; break; }
    echo "↻  Перезапускаю сессию $SID…"
    ARGS=(--resume "$SID")
    continue
  fi
  break
done
