#!/usr/bin/env bash
# Установка ccclean + ccclaude (обёртка с авто-чисткой) + хук PreCompact.
# Запуск:  ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS="$HOME/.claude/settings.json"
CFG_DIR="$HOME/.config/ccclean"
CFG="$CFG_DIR/config.json"

# Выбираем каталог из PATH, доступный на запись без sudo.
pick_bindir() {
  local d
  for d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
    case ":$PATH:" in *":$d:"*) :;; *) continue;; esac
    if [ -d "$d" ] && [ -w "$d" ]; then echo "$d"; return; fi
  done
  mkdir -p "$HOME/.local/bin"
  echo "ВНИМАНИЕ: добавь в PATH: export PATH=\"\$HOME/.local/bin:\$PATH\"" >&2
  echo "$HOME/.local/bin"
}
BINDIR="$(pick_bindir)"

# 1. Команды ccclean и ccclaude (симлинки в PATH)
chmod +x "$SCRIPT_DIR/ccclean.py" "$SCRIPT_DIR/ccclaude.sh"
ln -sf "$SCRIPT_DIR/ccclean.py"  "$BINDIR/ccclean"
ln -sf "$SCRIPT_DIR/ccclaude.sh" "$BINDIR/ccclaude"
echo "Установлено: $BINDIR/ccclean, $BINDIR/ccclaude"

# 2. Хуки (копируем в ~/.claude/hooks)
mkdir -p "$HOOKS_DIR"
cp "$SCRIPT_DIR/ccclean-hook.sh"      "$HOOKS_DIR/ccclean-hook.sh"
cp "$SCRIPT_DIR/ccclean-stop-hook.sh" "$HOOKS_DIR/ccclean-stop-hook.sh"
chmod +x "$HOOKS_DIR/ccclean-hook.sh" "$HOOKS_DIR/ccclean-stop-hook.sh"
echo "Хуки: ccclean-hook.sh (PreCompact), ccclean-stop-hook.sh (Stop)"

# 3. Регистрация хуков в settings.json + авто-компакт-настройки (идемпотентно)
mkdir -p "$(dirname "$SETTINGS")"
PRECOMPACT_CMD="$HOOKS_DIR/ccclean-hook.sh" STOP_CMD="$HOOKS_DIR/ccclean-stop-hook.sh" \
python3 - "$SETTINGS" <<'PY'
import json, os, sys
path = sys.argv[1]
pre_cmd = os.environ["PRECOMPACT_CMD"]
stop_cmd = os.environ["STOP_CMD"]
try:
    with open(path) as f: s = json.load(f)
except (OSError, json.JSONDecodeError):
    s = {}
s.setdefault("hooks", {})

def add(event, cmd, matcher=None):
    block = {"hooks": [{"type": "command", "command": cmd}]}
    if matcher is not None:
        block["matcher"] = matcher
    existing = s["hooks"].get(event, [])
    # выкидываем прежние НАШИ записи (по команде), чужие сохраняем
    existing = [b for b in existing
               if not any(h.get("command") == cmd for h in b.get("hooks", []))]
    s["hooks"][event] = existing + [block]

# PreCompact только на АВТО-компакт (ручной /compact не трогаем).
add("PreCompact", pre_cmd, matcher="auto")
# Stop — проактивный режим (активен, только если в config.json задан clean_at).
add("Stop", stop_cmd)
s["autoCompactEnabled"] = True       # нужно, чтобы PreCompact(auto) срабатывал сам
s["autoCompactWindow"] = 1000000     # окно на максимум → порог компакта почти у
                                     # реального потолка (~967k для 1M-модели)
with open(path, "w") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print("settings.json: хуки PreCompact+Stop зарегистрированы, autoCompactWindow=1M")
PY

# 4. Конфиг (права 600). Создаём при отсутствии и до-заполняем недостающие
#    дефолтные ключи в существующем (значения пользователя НЕ перезаписываем).
mkdir -p "$CFG_DIR"
SRC_CFG="$SCRIPT_DIR/config.json"; [ -f "$SRC_CFG" ] || SRC_CFG="$SCRIPT_DIR/config.example.json"
CFG="$CFG" SRC_CFG="$SRC_CFG" python3 - <<'PY'
import json, os
cfg = os.environ["CFG"]; src = os.environ["SRC_CFG"]
defaults = {"deepseek_api_key": "", "anthropic_api_key": "",
            "default_free": "50k", "usage_subtract": "200k", "clean_at": "940k", "resume_prompt": "continue", "loop_free": "10k"}
try:
    with open(src) as f: defaults.update({k: v for k, v in json.load(f).items()})
except Exception:
    pass
try:
    with open(cfg) as f: d = json.load(f)
    existed = True
except Exception:
    d = {}; existed = False
added = [k for k, v in defaults.items() if k not in d]
for k in added: d[k] = defaults[k]
with open(cfg, "w") as f: json.dump(d, f, ensure_ascii=False, indent=2)
os.chmod(cfg, 0o600)
print(f"Конфиг {'обновлён' if existed else 'создан'}: {cfg}"
      + (f" (добавлены: {', '.join(added)})" if added else ""))
PY

echo
echo "Готово. Перезапусти Claude Code, чтобы хук подхватился."
echo "Запускай сессии через:  ccclaude --resume <session-id>   (в терминале, не VS Code)"
