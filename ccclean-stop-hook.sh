#!/usr/bin/env bash
# ccclean-stop-hook.sh — ПРОАКТИВНЫЙ режим авто-чистки (хук Stop).
#
# Срабатывает после каждого ответа ассистента. Читает текущий usage из
# транскрипта и, если он выше порога clean_at (из ~/.config/ccclean/config.json),
# помечает сессию и завершает claude — чтобы обёртка ccclaude почистила её ДО
# того, как Claude Code упрётся в авто-компакт/блокировку.
#
# Режим включается наличием ключа "clean_at" в config.json (напр. "940k").
# Если ключа нет/пусто — хук ничего не делает (no-op).
# ВАЖНО: действуем только в сессиях, запущенных через обёртку ccclaude (она
# ставит CCCLEAN_WRAPPED=1). Иначе хук убивал бы любую сессию Claude Code.
[ -z "${CCCLEAN_WRAPPED:-}" ] && exit 0
INPUT=$(cat)

# Порог из конфига → в токенах. Пусто/нет → режим выключен.
THRESH=$(python3 - <<'PY' 2>/dev/null
import json, os
try:
    v = json.load(open(os.path.expanduser("~/.config/ccclean/config.json"))).get("clean_at")
except Exception:
    v = None
if not v:
    print(0); raise SystemExit
v = str(v).strip().lower(); mult = 1
if v.endswith("k"): mult, v = 1000, v[:-1]
elif v.endswith("m"): mult, v = 1000000, v[:-1]
try: print(int(float(v) * mult))
except Exception: print(0)
PY
)
{ [ -z "$THRESH" ] || [ "$THRESH" = "0" ]; } && exit 0   # режим выключен

SID=$(printf '%s' "$INPUT" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null)
TR=$(printf '%s' "$INPUT" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("transcript_path",""))' 2>/dev/null)
{ [ -z "$TR" ] || [ ! -f "$TR" ]; } && exit 0

# текущий usage = сумма последней usage-записи (как latest_usage_tokens)
USAGE=$(python3 - "$TR" <<'PY' 2>/dev/null
import sys, json
last = 0
for l in open(sys.argv[1], encoding="utf-8", errors="replace"):
    s = l.strip()
    if not s: continue
    try: o = json.loads(s)
    except Exception: continue
    m = o.get("message"); u = m.get("usage") if isinstance(m, dict) else None
    if isinstance(u, dict):
        t = u.get("input_tokens",0)+u.get("cache_read_input_tokens",0)+u.get("cache_creation_input_tokens",0)
        if t: last = t
print(last)
PY
)
{ [ -z "$USAGE" ] || [ "$USAGE" = "0" ]; } && exit 0

if [ "$USAGE" -gt "$THRESH" ]; then
  LOG="$HOME/.claude/ccclean-precompact.log"
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')  Stop: usage=$USAGE > clean_at=$THRESH → проактивная чистка sid=$SID ===" >> "$LOG"
  [ -n "$SID" ] && printf '%s' "$SID" > "$HOME/.claude/ccclean-pending"
  # завершить процесс claude среди предков → обёртка ccclaude подхватит
  pid=$PPID
  for _ in 1 2 3 4 5 6 7 8; do
    { [ -z "$pid" ] || [ "$pid" = "1" ]; } && break
    comm=$(ps -o comm= -p "$pid" 2>/dev/null)
    case "$comm" in *claude*) echo "  killing claude pid=$pid" >> "$LOG"; kill "$pid" 2>/dev/null; break;; esac
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  done
  echo "♻️ Контекст $USAGE > $THRESH — выхожу для проактивной чистки ccclean…" >&2
fi
exit 0
