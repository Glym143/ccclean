#!/usr/bin/env bash
# ccclean-hook.sh — хук Claude Code на событие PreCompact.
#
# Вместо встроенного компакта (который сжимает весь диалог в резюме) этот хук:
#   1) помечает текущую сессию (session_id → ~/.claude/ccclean-pending),
#   2) завершает процесс claude (exit 2 блокирует сам компакт),
# после чего обёртка `ccclaude` чистит сессию через `ccclean` и перезапускает её.
#
# Регистрируется в ~/.claude/settings.json на PreCompact (matcher auto —
# ручной /compact не перехватываем).
INPUT=$(cat)
LOG="$HOME/.claude/ccclean-precompact.log"
SID=$(printf '%s' "$INPUT" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null)
TRIGGER=$(printf '%s' "$INPUT" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("trigger","?"))' 2>/dev/null)
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')  PreCompact trigger=$TRIGGER sid=$SID ==="
  echo "$INPUT"; echo
} >> "$LOG"

# пометка для обёртки
[ -n "$SID" ] && printf '%s' "$SID" > "$HOME/.claude/ccclean-pending"

# найти процесс claude среди предков и завершить (чтобы он вышел в обёртку)
pid=$PPID
for _ in 1 2 3 4 5 6 7 8; do
  { [ -z "$pid" ] || [ "$pid" = "1" ]; } && break
  comm=$(ps -o comm= -p "$pid" 2>/dev/null)
  case "$comm" in
    *claude*) echo "  killing claude pid=$pid ($comm)" >> "$LOG"; kill "$pid" 2>/dev/null; break;;
  esac
  pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
done

echo "♻️ Контекст полон — выхожу для авто-чистки через ccclean…" >&2
exit 2
