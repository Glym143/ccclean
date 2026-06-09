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
FREE="${CCCLEAN_FREE:-10k}"   # сколько токенов срезать за один раз
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
