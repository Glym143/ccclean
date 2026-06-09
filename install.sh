#!/usr/bin/env bash
# Установка ccclean как глобальной команды (вариант: симлинк в каталог из PATH).
# Запуск:  ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/ccclean.py"
NAME="ccclean"

if [ ! -f "$SRC" ]; then
  echo "Не найден $SRC" >&2; exit 1
fi
chmod +x "$SRC"

# Выбираем каталог из PATH, доступный на запись без sudo.
TARGET_DIR=""
for d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
  case ":$PATH:" in *":$d:"*) :;; *) continue;; esac
  if [ -d "$d" ] && [ -w "$d" ]; then TARGET_DIR="$d"; break; fi
done
# Фолбэк: ~/.local/bin (создадим и подскажем добавить в PATH).
if [ -z "$TARGET_DIR" ]; then
  TARGET_DIR="$HOME/.local/bin"
  mkdir -p "$TARGET_DIR"
  echo "ВНИМАНИЕ: добавь в PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

ln -sf "$SRC" "$TARGET_DIR/$NAME"
echo "Установлено: $TARGET_DIR/$NAME -> $SRC"

# Конфиг с ключами (права 600).
CFG_DIR="$HOME/.config/ccclean"
CFG="$CFG_DIR/config.json"
SRC_CFG="$SCRIPT_DIR/config.json"
mkdir -p "$CFG_DIR"
if [ -f "$CFG" ]; then
  echo "Конфиг уже есть, не трогаю: $CFG"
elif [ -f "$SRC_CFG" ]; then
  # рядом лежит config.json с ключами — копируем его в нужное место
  cp "$SRC_CFG" "$CFG"
  chmod 600 "$CFG"
  echo "Конфиг скопирован из папки: $SRC_CFG -> $CFG"
else
  cat > "$CFG" <<'JSON'
{
  "deepseek_api_key": "",
  "anthropic_api_key": ""
}
JSON
  chmod 600 "$CFG"
  echo "Создан пустой конфиг: $CFG — впиши deepseek_api_key и anthropic_api_key"
fi

echo "Готово. Проверь: $NAME --help"
