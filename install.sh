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

# 2. Хук PreCompact (копируем в ~/.claude/hooks)
mkdir -p "$HOOKS_DIR"
cp "$SCRIPT_DIR/ccclean-hook.sh" "$HOOKS_DIR/ccclean-hook.sh"
chmod +x "$HOOKS_DIR/ccclean-hook.sh"
echo "Хук: $HOOKS_DIR/ccclean-hook.sh"

# 3. Регистрация хука в settings.json + включение авто-компакта (идемпотентно)
mkdir -p "$(dirname "$SETTINGS")"
HOOK_CMD="$HOOKS_DIR/ccclean-hook.sh" python3 - "$SETTINGS" <<'PY'
import json, os, sys
path = sys.argv[1]
cmd = os.environ["HOOK_CMD"]
try:
    with open(path) as f: s = json.load(f)
except (OSError, json.JSONDecodeError):
    s = {}
s.setdefault("hooks", {})
# PreCompact только на АВТО-компакт. Ручной /compact не трогаем — раз человек
# сам его запустил, значит компакт ему и нужен.
blocks = [{"matcher": "auto", "hooks": [{"type": "command", "command": cmd}]}]
existing = s["hooks"].get("PreCompact", [])
# выкидываем прежние НАШИ записи (по команде), чужие сохраняем
existing = [b for b in existing
           if not any(h.get("command") == cmd for h in b.get("hooks", []))]
s["hooks"]["PreCompact"] = existing + blocks
s["autoCompactEnabled"] = True       # нужно, чтобы PreCompact(auto) срабатывал сам
s["autoCompactWindow"] = 1000000     # окно на максимум → порог компакта почти у
                                     # реального потолка (~967k для 1M-модели),
                                     # меньше преждевременных «context limit reached»
with open(path, "w") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)
print("settings.json: PreCompact-хук зарегистрирован, autoCompactEnabled=true")
PY

# 4. Конфиг с ключами (права 600)
mkdir -p "$CFG_DIR"
if [ -f "$CFG" ]; then
  echo "Конфиг уже есть, не трогаю: $CFG"
elif [ -f "$SCRIPT_DIR/config.json" ]; then
  cp "$SCRIPT_DIR/config.json" "$CFG"; chmod 600 "$CFG"
  echo "Конфиг скопирован: $CFG"
else
  cp "$SCRIPT_DIR/config.example.json" "$CFG"; chmod 600 "$CFG"
  echo "Создан конфиг из шаблона: $CFG — впиши ключи deepseek_api_key и anthropic_api_key"
fi

echo
echo "Готово. Перезапусти Claude Code, чтобы хук подхватился."
echo "Запускай сессии через:  ccclaude --resume <session-id>   (в терминале, не VS Code)"
