#!/usr/bin/env python3
"""
ccclean — обрезка контекста сессии Claude Code.

Удаляет старые сообщения с начала активной ветки диалога, чтобы освободить
место в окне контекста. Работает напрямую с .jsonl-файлом сессии.

Как Claude Code строит контекст: грузится не весь файл, а только активная
цепочка — от последнего сообщения (листа) назад по parentUuid к корню.
Поэтому мы режем именно префикс этой цепочки и переподшиваем новый корень.

Подсчёт токенов:
  - по умолчанию точный через официальный Anthropic API
    (/v1/messages/count_tokens) — нужен ключ ANTHROPIC_API_KEY и сеть;
  - с флагом --fast используется tiktoken (cl100k_base) — быстро, офлайн,
    приблизительно (на кириллице занижает ~вдвое);
  - если точный недоступен (нет ключа/пакета) — мягкий фолбэк на tiktoken.

Примеры:
    ccclean                       # выбор сессии из списка + срез 10k (по умолч.)
    ccclean 30k                   # выбор сессии + срез 30k
    ccclean <session-id>          # эта сессия + срез 10k
    ccclean <session-id> 30k      # эта сессия + срез 30k
    ccclean <session-id> --keep 200k     # оставить последние ~200k
    ccclean <session-id> 50k --dry-run   # только показать план + резюме
    ccclean <session-id> 100k --fast     # быстрый tiktoken вместо API

Объём можно задать позиционно (30k, 50000, 1.5m) или флагом --free/--keep
(флаг имеет приоритет). Порядок аргументов не важен.
"""
import argparse
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Конфиг с ключами (создаётся install.sh, права 600). Ключи можно также
# задавать через переменные окружения — они имеют приоритет.
CONFIG_PATH = os.path.expanduser("~/.config/ccclean/config.json")


def get_config():
    """Читает ~/.config/ccclean/config.json (если есть)."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def get_key(env_name, config_name):
    """Ключ: сначала из переменной окружения, потом из конфига."""
    return os.environ.get(env_name) or get_config().get(config_name)


# ── автоустановка пакетов ──────────────────────────────────────────────────
def ensure_package(pkg, import_name=None, auto=None):
    """Импортирует пакет; если его нет — предлагает/выполняет установку через pip."""
    import_name = import_name or pkg
    try:
        return __import__(import_name)
    except ImportError:
        if auto is None:
            ans = input(f"Пакет '{pkg}' не установлен. Установить сейчас? [Y/n] ").strip().lower()
            auto = ans in ("", "y", "yes", "д", "да")
        if not auto:
            return None
        print(f"Устанавливаю '{pkg}'...")
        ok = False
        for extra in ([], ["--user"]):  # на managed-Python (PEP 668) пробуем --user
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", *extra, pkg])
                ok = True
                break
            except subprocess.CalledProcessError as e:
                last = e
        if not ok:
            print(f"Не удалось установить '{pkg}': {last}")
            return None
        try:
            return __import__(import_name)
        except ImportError:
            print(f"'{pkg}' установлен, но импорт не удался.")
            return None


# ── саммаризация через DeepSeek (OpenAI-совместимый API) ───────────────────
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def deepseek_chat(messages, key, model="deepseek-v4-flash", max_tokens=3000):
    """Один запрос к DeepSeek chat/completions через stdlib (без зависимостей)."""
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        DEEPSEEK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read().decode("utf-8"))
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        # пустой/нестандартный ответ — не роняем весь рез из-за резюме
        raise RuntimeError(f"неожиданный ответ DeepSeek: {str(data)[:200]}")


# Системный промпт-резюмировщик. За основу взят встроенный промпт компактизации
# Claude Code, но цель другая: не безпотерьное продолжение работы, а КРАТКОЕ
# резюме, по которому пользователь решает — можно ли удалить фрагмент из контекста.
SUMMARY_SYSTEM = (
    "Ты кратко резюмируешь фрагмент диалога между пользователем и ИИ-ассистентом. "
    "Цель — сжать содержание так, чтобы человек сам понял, о чём шла речь. "
    "Не оценивай важность и не советуй удалять/сохранять — только излагай суть. "
    "Не уходи в ультра-детали, без длинных дампов кода. Пиши по-русски."
)

# Инструкция формирования КРАТКОГО резюме удаляемого фрагмента (без <analysis>).
SUMMARY_FORMAT = """\
Сделай краткое резюме — по 1-3 пункта на секцию, чтобы было понятно, о чём речь,
без длинных сниппетов (только ключевые имена файлов/функций). Секции:
1. О чём фрагмент: главные запросы пользователя и темы.
2. Ключевые технические детали: файлы/функции/решения (кратко, списком).
3. Ошибки и важный фидбэк пользователя (если были; иначе пропусти).
4. Незавершённые задачи (если есть).
5. Security-инструкции/ограничения — ДОСЛОВНО (если были; иначе «нет»).

Не оценивай важность фрагмента и не давай рекомендаций по удалению.
Пиши сразу резюме, без размышлений и без служебных тегов."""


def extract_summary(text):
    """Вырезает содержимое <summary>…</summary>; если тегов нет — режет <analysis>."""
    lo = text.find("<summary>")
    hi = text.rfind("</summary>")
    if lo != -1 and hi != -1 and hi > lo:
        return text[lo + len("<summary>"):hi].strip()
    # фолбэк: убрать блок <analysis>…</analysis>, если он есть
    a, b = text.find("<analysis>"), text.find("</analysis>")
    if a != -1 and b != -1 and b > a:
        return (text[:a] + text[b + len("</analysis>"):]).strip()
    return text.strip()


def _chunk_texts(texts, chunk_chars):
    """Бьёт список сообщений на куски не длиннее chunk_chars символов."""
    chunks, cur = [], ""
    for t in texts:
        if not t:
            continue
        if len(cur) + len(t) > chunk_chars and cur:
            chunks.append(cur)
            cur = t
        else:
            cur += ("\n\n" + t if cur else t)
    if cur:
        chunks.append(cur)
    return chunks


def summarize_removed(texts, key, model="deepseek-v4-flash"):
    """Резюмирует удаляемый фрагмент по структуре промпта Claude Code.
    При большом объёме — map-reduce: извлекаем детали по кускам, затем сводим."""
    CHUNK = 120000  # символов на кусок (у V4 контекст 1M — режем крупно)
    chunks = _chunk_texts(texts, CHUNK)
    if not chunks:
        return "(пусто — нечего резюмировать)"

    if len(chunks) == 1:
        prompt = ("Ниже — фрагмент диалога, который собираются УДАЛИТЬ из контекста.\n"
                  f"{SUMMARY_FORMAT}\n\n=== ФРАГМЕНТ ===\n{chunks[0]}")
        return deepseek_chat(
            [{"role": "system", "content": SUMMARY_SYSTEM},
             {"role": "user", "content": prompt}], key, model)

    # map: подробно извлекаем факты из каждого куска
    partials = []
    for i, ch in enumerate(chunks):
        prompt = (f"Часть {i+1} из {len(chunks)} удаляемого фрагмента. Подробно "
                  "извлеки: запросы пользователя, технические детали, файлы/код "
                  "(сигнатуры, сниппеты, адреса), ошибки/исправления, security-"
                  f"инструкции дословно, незакрытые вопросы:\n\n{ch}")
        partials.append(deepseek_chat(
            [{"role": "system", "content": SUMMARY_SYSTEM},
             {"role": "user", "content": prompt}], key, model))
    # reduce: сводим в единое структурное резюме
    combined = "\n\n".join(f"[Часть {i+1}]\n{p}" for i, p in enumerate(partials))
    prompt = ("Ниже — извлечённые факты по частям удаляемого фрагмента диалога. "
              f"Сведи их в одно цельное резюме.\n{SUMMARY_FORMAT}\n\n"
              f"=== ФАКТЫ ПО ЧАСТЯМ ===\n{combined}")
    return deepseek_chat(
        [{"role": "system", "content": SUMMARY_SYSTEM},
         {"role": "user", "content": prompt}], key, model)


# ── токенизаторы ───────────────────────────────────────────────────────────
def make_tiktoken_counter(assume_yes):
    """Возвращает (count_fn, описание). tiktoken cl100k_base, иначе фолбэк."""
    tk = ensure_package("tiktoken", auto=(True if assume_yes else None))
    if tk is not None:
        try:
            enc = tk.get_encoding("cl100k_base")
            def count(text):
                if not text:
                    return 0
                return len(enc.encode(text, disallowed_special=()))
            return count, "tiktoken/cl100k_base (приблизительно)"
        except Exception as e:
            print(f"tiktoken есть, но не загрузился ({e}); фолбэк на символы÷2.")
    def count(text):
        if not text:
            return 0
        return max(1, len(text) // 2)  # кириллица ≈2 симв/токен
    return count, "fallback символы÷2"


class ExactPrefixCounter:
    """Точный подсчёт префиксов через официальный API count_tokens.

    Чтобы не слать по запросу на каждое сообщение, считаем префикс целиком:
    конкатенируем текст первых k сообщений в одно user-сообщение и считаем его.
    Это валидный запрос (одно сообщение) и позволяет бинарный поиск точки реза
    за ~log2(N) обращений к API."""

    def __init__(self, client, model, texts):
        self.client = client
        self.model = model
        self.texts = texts
        self.cache = {0: 0}

    def prefix(self, k):
        if k in self.cache:
            return self.cache[k]
        text = "\n".join(t for t in self.texts[:k] if t)
        if not text:
            self.cache[k] = 0
            return 0
        r = self.client.messages.count_tokens(
            model=self.model,
            messages=[{"role": "user", "content": text}],
        )
        self.cache[k] = r.input_tokens
        return r.input_tokens


# ── разбор аргументов количества ───────────────────────────────────────────
_AMOUNT_RE = re.compile(r"^\d+(\.\d+)?[km]?$")  # 100000, 10k, 1.5m


def is_amount(s):
    """True, если строка похожа на объём токенов: 10k, 50000, 1.5m.
    Строгий шаблон — не принимает nan/inf/1e3 и session-id."""
    return bool(_AMOUNT_RE.match(s.strip().lower()))


def parse_amount(s):
    """Разбирает '100000', '100k', '1.5m' в число токенов."""
    s = str(s).strip().lower().replace("_", "")
    if not _AMOUNT_RE.match(s):
        sys.exit(f"Неверный объём: '{s}'. Примеры: 10k, 50000, 1.5m")
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    return int(float(s) * mult)


# ── работа с записями сессии ───────────────────────────────────────────────
def msg_text(o):
    """Собирает весь текст записи, влияющий на контекст:
    текст, рассуждения (thinking), аргументы tool_use, содержимое tool_result."""
    m = o.get("message", {})
    if not isinstance(m, dict):
        return ""
    c = m.get("content")
    if isinstance(c, str):
        return c
    if not isinstance(c, list):
        return ""
    parts = []
    for b in c:
        if not isinstance(b, dict):
            continue
        if b.get("text"):
            parts.append(b["text"])
        if b.get("type") == "thinking":  # extended thinking тоже в контексте
            parts.append(b.get("thinking", "") or "")
        if b.get("type") == "tool_use":
            parts.append(json.dumps(b.get("input", {}), ensure_ascii=False))
        rc = b.get("content")
        if isinstance(rc, str):
            parts.append(rc)
        elif isinstance(rc, list):
            for x in rc:
                if isinstance(x, dict) and x.get("text"):
                    parts.append(x["text"])
    return "\n".join(parts)


def _img_dims(data_b64):
    """Размеры (w,h) картинки из base64 по заголовку PNG/JPEG/GIF.
    Декодируем целиком: у JPEG маркер SOF может быть далеко за EXIF/ICC-сегментами."""
    try:
        pad = "=" * (-len(data_b64) % 4)  # корректный padding
        raw = base64.b64decode(data_b64 + pad)
    except Exception:
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        return struct.unpack(">II", raw[16:24])
    if raw[:2] == b"\xff\xd8":  # JPEG: ищем SOF-маркер
        i = 2
        while i < len(raw) - 9:
            if raw[i] != 0xFF:
                i += 1
                continue
            marker = raw[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return w, h
            i += 2 + struct.unpack(">H", raw[i + 2:i + 4])[0]
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", raw[6:10])
    return None


def image_tokens_of(o):
    """Токены картинок записи по формуле Anthropic: ~ (w*h)/750
    (с учётом ресайза по длинной стороне до 1568px). Фолбэк ~1500/картинку."""
    total = 0

    def scan(blocks):
        nonlocal total
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "image":
                src = b.get("source", {})
                dims = _img_dims(src.get("data", "")) if src.get("type") == "base64" else None
                if dims:
                    w, h = dims
                    m = max(w, h)
                    if m > 1568:  # Anthropic ужимает длинную сторону до 1568
                        w, h = int(w * 1568 / m), int(h * 1568 / m)
                    total += (w * h) // 750
                else:
                    total += 1500
            rc = b.get("content")
            if isinstance(rc, list):
                scan(rc)

    m = o.get("message", {})
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, list):
        scan(c)
    return total


def resolve_path(session, projects_dir):
    """Принимает путь к .jsonl, полный session-id или его префикс (как в меню, 8 симв)."""
    if os.path.isfile(session):
        return session
    sid = session[:-6] if session.endswith(".jsonl") else session
    exact, prefix = [], []
    for root, _dirs, files in os.walk(projects_dir):
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            name = fn[:-6]
            if name == sid:
                exact.append(os.path.join(root, fn))
            elif name.startswith(sid):  # короткий id из листинга
                prefix.append(os.path.join(root, fn))
    matches = exact or prefix  # точное совпадение приоритетнее префикса
    if not matches:
        sys.exit(f"Не найдена сессия '{sid}' в {projects_dir}")
    if len(matches) > 1:
        sys.exit("Найдено несколько сессий, уточни id:\n  " + "\n  ".join(matches))
    return matches[0]


def session_in_use(path):
    """Процессы, держащие файл сессии открытым (через lsof).
    Если сессию держит Claude Code / VS Code — рез не применится: контекст
    в памяти процесса перезапишет файл. Возвращает список (команда, PID)."""
    if not shutil.which("lsof"):
        return []
    try:
        r = subprocess.run(["lsof", "--", path], capture_output=True,
                            text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    procs, seen = [], set()
    for line in r.stdout.splitlines()[1:]:  # пропускаем заголовок
        parts = line.split()
        if len(parts) >= 2 and parts[1] not in seen:
            seen.add(parts[1])
            procs.append((parts[0], parts[1]))
    return procs


def session_title(path):
    """Заголовок сессии: текст первого осмысленного сообщения пользователя
    (или summary-записи), пропуская служебные caveat-блоки."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    o = json.loads(s)
                except json.JSONDecodeError:
                    continue
                if o.get("type") == "summary" and o.get("summary"):
                    return o["summary"].strip()
                if o.get("type") == "user":
                    m = o.get("message", {})
                    c = m.get("content") if isinstance(m, dict) else None
                    txt = c if isinstance(c, str) else ""
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("text"):
                                txt = b["text"]
                                break
                    txt = txt.strip()
                    if txt and not txt.startswith("<"):  # пропускаем caveat
                        return txt
    except OSError:
        pass
    return "(без заголовка)"


def list_sessions(projects_dir):
    """Все сессии во всех проектах, отсортированы по времени изменения (свежие выше).
    Служебные транскрипты сабагентов (agent-*) пропускаются."""
    items = []
    for root, _dirs, files in os.walk(projects_dir):
        for fn in files:
            if not fn.endswith(".jsonl") or fn.startswith("agent-"):
                continue
            p = os.path.join(root, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            items.append({
                "path": p,
                "sid": fn[:-6],
                "mtime": st.st_mtime,
                "size": st.st_size,
                "project": os.path.basename(root),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def ensure_fzf(auto=None):
    """Проверяет наличие fzf; если нет — предлагает/ставит через brew/apt/dnf."""
    if shutil.which("fzf"):
        return True
    if auto is None:
        try:
            ans = input("fzf не установлен — поставить для удобного выбора? [Y/n] ")
        except (EOFError, KeyboardInterrupt):
            return False
        auto = ans.strip().lower() in ("", "y", "yes", "д", "да")
    if not auto:
        return False
    if shutil.which("brew"):
        cmd = ["brew", "install", "fzf"]
    elif shutil.which("apt-get"):
        cmd = ["sudo", "apt-get", "install", "-y", "fzf"]
    elif shutil.which("dnf"):
        cmd = ["sudo", "dnf", "install", "-y", "fzf"]
    else:
        print("Не нашёл brew/apt/dnf — поставь fzf вручную. Пока меню по номеру.")
        return False
    print("Устанавливаю fzf:", " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"Не удалось установить fzf: {e}. Меню по номеру.")
        return False
    return shutil.which("fzf") is not None


def _fmt_session_row(it):
    """Строка списка: дата, размер, короткий id, заголовок."""
    mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(it["mtime"]))
    mb = it["size"] / (1024 * 1024)
    title = session_title(it["path"]).replace("\n", " ").replace("\t", " ")
    if len(title) > 80:
        title = title[:79] + "…"
    return f"{mt}  {mb:5.1f}MB  {it['sid'][:8]}  {title}"


def pick_session(projects_dir, limit=60, assume_yes=False):
    """Интерактивный выбор сессии: через fzf (если есть/ставится), иначе меню по номеру."""
    items = list_sessions(projects_dir)[:limit]
    if not items:
        sys.exit(f"Сессии не найдены в {projects_dir}")

    # fzf: красивый выбор с поиском по заголовку (ставим, если отсутствует)
    if ensure_fzf(auto=(True if assume_yes else None)):
        # индекс в начале строки → по нему находим путь после выбора
        lines = [f"{i}\t{_fmt_session_row(it)}" for i, it in enumerate(items)]
        try:
            proc = subprocess.run(
                ["fzf", "--with-nth=2..", "--delimiter=\t",
                 "--prompt=Сессия> ", "--height=80%", "--reverse",
                 "--header=Выбери сессию для очистки (поиск по заголовку)"],
                input="\n".join(lines), capture_output=True, text=True)
        except OSError:
            proc = None
        if proc and proc.returncode == 0 and proc.stdout.strip():
            idx = int(proc.stdout.split("\t", 1)[0])
            return items[idx]["path"]
        sys.exit("Отмена.")

    # фолбэк: пронумерованное меню
    print(f"Сессии (свежие сверху), всего показано {len(items)}:\n")
    for i, it in enumerate(items, 1):
        print(f"{i:>3}. {_fmt_session_row(it)}")
    print()
    try:
        raw = input("Введи номер сессии (Enter — отмена): ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit("\nОтмена.")
    if not raw:
        sys.exit("Отмена.")
    if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
        sys.exit("Неверный номер.")
    return items[int(raw) - 1]["path"]


def load(path):
    """Читает .jsonl, сохраняя сырые строки (чтобы не терять неизменённые записи)."""
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f.read().splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                recs.append((line, json.loads(s)))
            except json.JSONDecodeError:
                recs.append((line, None))
    return recs


def active_chain(objs):
    """Восстанавливает активную цепочку от самого позднего листа к корню."""
    by_uuid = {o["uuid"]: o for o in objs if o.get("uuid")}
    children = {o.get("parentUuid") for o in objs if o.get("parentUuid")}
    leaves = [o for o in objs
              if o.get("uuid") and o["uuid"] not in children
              and o.get("type") in ("user", "assistant")]
    if not leaves:
        sys.exit("Не найдено ни одного листа диалога — файл пуст или повреждён.")
    leaf = sorted(leaves, key=lambda o: o.get("timestamp") or "")[-1]
    chain, cur, seen = [], leaf, set()
    while cur and cur.get("uuid") not in seen:
        seen.add(cur["uuid"])
        chain.append(cur)
        cur = by_uuid.get(cur.get("parentUuid"))
    chain.reverse()
    return chain, by_uuid


def latest_usage_tokens(objs):
    """Реальный объём контекста по логам: usage последнего ответа ассистента
    (input + cache_read + cache_creation). Это то, что показывает полоса Claude Code
    и что включает системный промпт, схемы инструментов, MCP, CLAUDE.md и т.д."""
    last = None
    for o in objs:
        m = o.get("message", {})
        u = m.get("usage") if isinstance(m, dict) else None
        if isinstance(u, dict) and (u.get("input_tokens") or u.get("cache_read_input_tokens")):
            last = u
    if not last:
        return None
    return (last.get("input_tokens", 0)
            + last.get("cache_read_input_tokens", 0)
            + last.get("cache_creation_input_tokens", 0))


def reduce_usage(u, amount):
    """Уменьшает счётчик токенов в usage-словаре на amount (вычитаем из самых
    крупных составляющих: cache_read → cache_creation → input). Зеркалит в
    iterations[]. Это снимает блок «context limit reached» у Claude Code, который
    читает usage последнего ответа, а не пересчитывает урезанные сообщения."""
    def _sub(d, left):
        for k in ("cache_read_input_tokens", "cache_creation_input_tokens",
                  "input_tokens"):
            if left <= 0:
                break
            v = d.get(k, 0)
            take = min(v, left)
            d[k] = v - take
            left -= take
        return left
    _sub(u, amount)
    for it in u.get("iterations", []) or []:
        if isinstance(it, dict):
            _sub(it, amount)


def usage_total(u):
    """Сумма токенов контекста в usage-словаре (как считает Claude Code)."""
    return (u.get("input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0))


def detect_model(objs, default="claude-opus-4-8"):
    """Достаёт id модели из записей сессии (для точного подсчёта через API)."""
    for o in objs:
        m = o.get("message", {})
        if isinstance(m, dict) and isinstance(m.get("model"), str) and m["model"].startswith("claude"):
            return m["model"]
    return default


def smallest_k_ge(n, target, prefix_fn):
    """Наименьшее k в [0..n], при котором prefix_fn(k) >= target (бинарный поиск)."""
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if prefix_fn(mid) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


# ── main ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Обрезка контекста сессии Claude Code (удаление старых сообщений с начала).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("args", nargs="*",
                    help="session-id/путь и/или объём (напр. 30k). "
                         "Без объёма — 10k; без сессии — выбор из списка")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--free", help="сколько токенов освободить с начала "
                                  "(напр. 100k, 50000, 1.5m; по умолчанию 10k)")
    g.add_argument("--keep", help="оставить последние N токенов, остальное с начала срезать")
    ap.add_argument("--fast", action="store_true",
                    help="быстрый приблизительный подсчёт через tiktoken "
                         "(по умолчанию — точный через Anthropic API)")
    ap.add_argument("--model", help="модель для точного подсчёта (по умолчанию берётся из сессии)")
    ap.add_argument("--projects-dir",
                    default=os.path.expanduser("~/.claude/projects"),
                    help="папка с проектами Claude Code (по умолч. ~/.claude/projects)")
    ap.add_argument("--no-summary", action="store_true",
                    help="не делать саммаризацию удаляемого через DeepSeek")
    ap.add_argument("--ds-model", default="deepseek-v4-flash", help="модель DeepSeek для резюме")
    ap.add_argument("--dry-run", action="store_true", help="показать план, ничего не менять")
    ap.add_argument("--no-backup", action="store_true", help="не создавать .bak")
    ap.add_argument("--force", action="store_true",
                    help="резать, даже если сессия открыта (НЕ рекомендуется)")
    ap.add_argument("-y", "--yes", action="store_true", help="не спрашивать подтверждение")
    args = ap.parse_args()

    # Разбираем позиционные: что похоже на объём — объём, остальное — сессия.
    session = None
    pos_amount = None
    for a in args.args:
        if is_amount(a):
            pos_amount = a
        else:
            session = a

    # Объём: приоритет у --free/--keep, затем позиционный, затем default_free
    # из ~/.config/ccclean/config.json, затем 10k.
    if not args.free and not args.keep:
        args.free = pos_amount or get_config().get("default_free") or "10k"

    if session:
        path = resolve_path(session, args.projects_dir)
    else:
        path = pick_session(args.projects_dir, assume_yes=args.yes)  # интерактивный выбор

    # ── защита: сессия не должна быть открыта (иначе рез не применится) ──
    # Предупреждаем только когда это РЕАЛЬНО проблема — т.е. сессия открыта и НЕТ
    # --force. С --force (авто-режим обёртки) молча продолжаем, без шума.
    if not args.force:
        holders = session_in_use(path)
        if holders:  # реальный открытый дескриптор — жёсткий блок
            print("⚠ Сессия СЕЙЧАС ОТКРЫТА — её держат процессы:")
            for cmd, pid in holders:
                print(f"    {cmd} (PID {pid})")
            print("Рез НЕ подействует: живая сессия перезапишет файл из памяти.")
            print("Закрой сессию полностью (или /compact прямо в ней).")
            sys.exit("Прервано. Обойти (на свой риск): --force")

    recs = load(path)
    objs = [o for _, o in recs if o]
    chain, _ = active_chain(objs)
    texts = [msg_text(o) for o in chain]
    msg_count = sum(1 for o in chain if o.get("type") in ("user", "assistant"))

    # Токены картинок считаем локально по формуле (в текстовый счёт не входят).
    img_cum = [0] * (len(chain) + 1)
    for i, o in enumerate(chain):
        img_cum[i + 1] = img_cum[i] + image_tokens_of(o)

    # ── выбираем счётчик ТЕКСТОВЫХ токенов и функцию префикса ──
    # По умолчанию — точный подсчёт через Anthropic API; --fast переключает на
    # tiktoken. Если точный недоступен (нет ключа/пакета) — мягкий фолбэк.
    text_prefix = None
    tok_desc = None
    if not args.fast:
        anthropic = ensure_package("anthropic", auto=(True if args.yes else None))
        an_key = get_key("ANTHROPIC_API_KEY", "anthropic_api_key")
        if anthropic is None:
            print("[!] Пакет 'anthropic' недоступен — фолбэк на tiktoken (--fast).")
        elif not an_key:
            print("[!] Нет ANTHROPIC_API_KEY (env или "
                  f"{CONFIG_PATH}) — фолбэк на tiktoken (--fast).")
        else:
            model = args.model or detect_model(objs)
            client = anthropic.Anthropic(api_key=an_key)
            counter = ExactPrefixCounter(client, model, texts)
            text_prefix = counter.prefix
            tok_desc = f"официальный API count_tokens (точно, модель {model})"

    if text_prefix is None:  # --fast или фолбэк
        count_fn, tok_desc = make_tiktoken_counter(args.yes)
        cum = [0] * (len(texts) + 1)
        for i, t in enumerate(texts):
            cum[i + 1] = cum[i] + count_fn(t)
        text_prefix = lambda k: cum[k]

    # Итоговый префикс = текст (+thinking) + картинки.
    prefix_fn = lambda k: text_prefix(k) + img_cum[k]

    total = prefix_fn(len(texts))
    if img_cum[-1]:
        tok_desc += f" + картинки ~{img_cum[-1]:,} ткн (формула)"

    print(f"Файл:        {path}")
    print(f"Токенизатор: {tok_desc}")
    real = latest_usage_tokens(objs)
    if real:
        print(f"Реально в окне (по логам, вкл. систему/инструменты/MCP): ~{real:,} токенов")
    print(f"Активная ветка (что можно срезать): {msg_count} сообщ. ≈ {total:,} токенов")
    if real and total < real * 0.7:
        print(f"  ⚠ срезать можно только ~{total:,} из ~{real:,} — остальное это "
              "системный промпт / схемы инструментов / MCP / CLAUDE.md (не убирается обрезкой).")

    # ── сколько целимся срезать ──
    if args.free:
        target = parse_amount(args.free)
    else:
        keep = parse_amount(args.keep)
        target = max(0, total - keep)
    if target <= 0:
        sys.exit("Нечего срезать (цель ≤ 0).")
    if target >= total:
        sys.exit(f"Цель ({target:,}) ≥ всего ({total:,}). Это снесёт весь диалог — отмена.")

    # ── ищем точку реза: префикс >= target, затем ближайшая граница user ──
    # Гарантируем, что реально срежем НЕ МЕНЬШЕ target: если на границе
    # префикс оказался ниже цели (возможная немонотонность count_tokens на
    # склейке текста), двигаемся к следующей user-границе.
    def next_user_cut(start):
        for i in range(start, len(chain)):
            if chain[i].get("type") == "user" and i > 0:
                return i
        return None

    k = smallest_k_ge(len(chain), target, prefix_fn)
    cut_idx = next_user_cut(k)
    while cut_idx is not None and prefix_fn(cut_idx) < target:
        nxt = next_user_cut(cut_idx + 1)
        if nxt is None:
            break
        cut_idx = nxt
    if cut_idx is None:
        sys.exit("Не нашёл границу (user-сообщение) после цели — попробуй меньший объём.")

    remove = {chain[i]["uuid"] for i in range(cut_idx)}
    new_root = chain[cut_idx]
    removed_tokens = prefix_fn(cut_idx)
    remaining = total - removed_tokens

    print(f"\nПлан резки:")
    print(f"  удалить записей цепочки: {len(remove)}")
    print(f"  освободится ≈ {removed_tokens:,} токенов")
    print(f"  новый корень: {new_root.get('type')} "
          f"ts={(new_root.get('timestamp') or '')[:19]}")
    print(f"  останется ≈ {remaining:,} токенов")

    # ── саммаризация удаляемого фрагмента через DeepSeek ──
    if not args.no_summary:
        ds_key = get_key("DEEPSEEK_API_KEY", "deepseek_api_key")
        if not ds_key:
            print("\n[!] Ключ DeepSeek не найден (DEEPSEEK_API_KEY или "
                  f"{CONFIG_PATH}). Резюме пропущено. Отключить: --no-summary")
        else:
            print("\nДелаю резюме удаляемого фрагмента через DeepSeek...")
            removed_texts = [texts[i] for i in range(cut_idx)]
            try:
                summary = extract_summary(
                    summarize_removed(removed_texts, ds_key, args.ds_model))
                print("\n" + "─" * 60)
                print("РЕЗЮМЕ УДАЛЯЕМОГО ФРАГМЕНТА:")
                print("─" * 60)
                print(summary)
                print("─" * 60)
            except Exception as e:  # резюме не критично — не роняем рез из-за него
                print(f"[!] Не удалось получить резюме от DeepSeek: {e}")

    if args.dry_run:
        print("\n[dry-run] изменения не записаны.")
        return

    if not args.yes:
        ans = input("\nУдалить этот фрагмент из контекста? [y/N] ").strip().lower()
        if ans not in ("y", "yes", "д", "да"):
            print("Отмена.")
            return

    if not args.no_backup:
        bak = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, bak)
        print(f"Бэкап: {bak}")

    # Находим последний ответ ассистента с usage в ОСТАВШЕЙСЯ ветке — именно его
    # счётчик читает Claude Code для проверки лимита.
    usage_uuid = None
    for o in reversed(chain[cut_idx:]):
        u = o.get("message", {}).get("usage") if isinstance(o.get("message"), dict) else None
        if o.get("type") == "assistant" and isinstance(u, dict) and usage_total(u) > 0:
            usage_uuid = o["uuid"]
            usage_before = usage_total(u)
            break

    # Сколько вычесть из usage. Эмпирически: чтобы авто-компакт не сработал перед
    # первым запросом после резюме, счётчик надо опустить заметно НИЖЕ реально
    # срезанного — на usage_subtract (по умолч. 100k, ключ в config.json). Берём
    # максимум из (реально срезано, usage_subtract) — это безопасно: реальный
    # контекст после реза всё равно < лимита, сервер примет запрос.
    usage_subtract = parse_amount(get_config().get("usage_subtract") or "200k")
    usage_drop = max(removed_tokens, usage_subtract)

    # ── пересборка файла: пропускаем удаляемые uuid; корню parentUuid=null ──
    out = []
    rerooted = False  # на случай дубля uuid переподшиваем только первую запись
    usage_after = None
    for raw, o in recs:
        if o and o.get("uuid") in remove:
            continue
        modified = False
        if o and not rerooted and o.get("uuid") == new_root["uuid"]:
            o["parentUuid"] = None
            rerooted = True
            modified = True
        if o and usage_uuid and o.get("uuid") == usage_uuid:
            reduce_usage(o["message"]["usage"], usage_drop)
            usage_after = usage_total(o["message"]["usage"])
            modified = True
        out.append(json.dumps(o, ensure_ascii=False) if modified else raw)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    if usage_after is not None:
        print(f"Счётчик usage последнего ответа: {usage_before:,} → {usage_after:,} "
              f"(−{usage_drop:,}; срезано {removed_tokens:,}) — снят блок limit reached")

    # ── контроль целостности новой цепочки ──
    objs2 = []
    for x in out:
        try:
            objs2.append(json.loads(x))
        except json.JSONDecodeError:
            pass  # битые строки игнорируем (как в load), не падаем
    chain2, by2 = active_chain(objs2)
    broken = any(o.get("parentUuid") is not None and o["parentUuid"] not in by2
                 for o in chain2[1:])
    msg_count2 = sum(1 for o in chain2 if o.get("type") in ("user", "assistant"))
    root2 = chain2[0]
    print(f"\nГотово. Целостность: {'OK' if not broken else 'РАЗРЫВ!'}")
    print(f"Корень: {root2.get('type')} parentUuid={root2.get('parentUuid')}")
    print(f"Активная ветка теперь: {msg_count2} сообщ.")
    print("Возобнови сессию: claude --resume " + os.path.basename(path)[:-6])


if __name__ == "__main__":
    main()
