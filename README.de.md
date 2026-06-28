<div align="center">

# ccclean

**Ein chirurgisch präziser Kontext-Bereiniger für Sitzungen mit [Claude Code](https://docs.anthropic.com/en/docs/claude-code).**
Schneide die ältesten Nachrichten einer Unterhaltung ab, um das Kontextfenster freizugeben — mit einem Bestätigungsschritt und einer optionalen Zusammenfassung dessen, was entfernt wird.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

[English](README.md) · [Русский](README.ru.md) · [中文](README.zh-CN.md) · [Español](README.es.md) · **Deutsch**

</div>

---

Es arbeitet direkt mit den `.jsonl`-Sitzungsdateien in `~/.claude/projects/`.

## Inhalt

- [Warum ccclean](#warum-ccclean)
- [Funktionen](#funktionen)
- [Installation](#installation)
  - [API-Schlüssel](#api-schlüssel)
- [Verwendung](#verwendung)
- [Automatische Bereinigung (der Hook + `ccclaude`)](#automatische-bereinigung-der-hook--ccclaude)
  - [Proaktiver Modus (`clean_at`)](#proaktiver-modus-clean_at)
  - [Automatisches Fortsetzen (`resume_prompt`)](#automatisches-fortsetzen-resume_prompt)
  - [Hook-Sicherheit](#hook-sicherheit)
- [Funktionsweise](#funktionsweise)
- [Für KI-Agenten](#für-ki-agenten)
- [Vorbehalte](#vorbehalte)
- [Lizenz](#lizenz)

---

## Warum ccclean

Lange Sitzungen mit Claude Code füllen das Kontextfenster, und die Arbeit wird
mühsamer: Das Modell stößt an seine Grenze, und die automatische Komprimierung
(Auto-Compact) setzt im ungünstigsten Moment ein und stampft alles wahllos
zusammen. `ccclean` gibt dir **präzise Kontrolle**: Du entscheidest, wie viele
Token freigegeben werden und welcher alte Abschnitt der Unterhaltung genau
entfällt — nachdem du zuvor eine kurze Zusammenfassung davon gesehen hast. Der
aktuelle (jüngste) Teil der Unterhaltung bleibt unberührt.

Anders als das eingebaute `/compact` (das den *gesamten* Dialog zu einer
Zusammenfassung komprimiert) **schneidet `ccclean` einfach den ältesten Anfang**
des aktiven Zweigs ab und behält die jüngsten Nachrichten wortgetreu bei.

---

## Funktionen

- ✂️ **Präzises Beschneiden** — du gibst eine Menge an (`10k`, `50k`, `1.5m`), und
  das Tool entfernt alte Nachrichten vom Anfang her, sodass **mindestens** die
  angeforderte Menge freigegeben wird.
- 🔢 **Ehrliche Token-Zählung** — standardmäßig über die offizielle
  Anthropic-`count_tokens`-API (exakt) oder offline via `tiktoken` (`--fast`).
  Sie berücksichtigt Text, `thinking`, Tool-Aufrufe und **Bilder**.
- 📋 **Zusammenfassung des Entfernten (optional)** — mit dem `--summary`-Flag zeigt
  das Tool, bevor es irgendetwas löscht, eine kurze Zusammenfassung des Abschnitts
  an (via DeepSeek), damit du verstehst, was du verlierst. Standardmäßig
  deaktiviert.
- 📊 **Tatsächliche Fensterauslastung** — zeigt die reale Kontextgröße aus den Logs
  (`usage`) an, einschließlich System-Prompt, Tool-Schemata, MCP und `CLAUDE.md`.
- 🗂 **Interaktive Sitzungsauswahl** — ohne Argumente öffnet sich eine Liste der
  Unterhaltungen (via `fzf`, nach Titel durchsuchbar), sodass du dir die ID nicht
  merken musst.
- 🔓 **Hebt die Sperre „Kontextlimit erreicht“ auf** — Claude Code bestimmt das
  Limit aus dem `usage` der letzten Antwort, statt die beschnittenen Nachrichten
  neu zu zählen. Nach einem Schnitt senkt ccclean diesen Zähler um
  `usage_subtract` (Standard `200k`, ein Schlüssel in `config.json`) — spürbar
  unter das, was tatsächlich entfernt wurde, sodass Auto-Compact vor der ersten
  Anfrage nach der Bereinigung nicht auslöst. Der reale Kontext liegt weiterhin
  unter dem Limit, also nimmt der Server die Anfrage an, und Claude Code zählt den
  Zähler aus den tatsächlichen Daten neu.
- 💾 **Sicherheit** — ein automatisches Backup vor jedem Schnitt, eine
  Integritätsprüfung, Schutz davor, den gesamten Dialog zu löschen, und ein
  korrektes Wieder-Verknüpfen der Wurzel.

---

## Installation

Du benötigst **Python 3.8+** und `pip`. Alles Weitere (`tiktoken`, `anthropic`,
`fzf`) installiert das Tool beim ersten Start selbst.

```bash
git clone https://github.com/Glym143/ccclean.git
cd ccclean
./install.sh
```

`install.sh`:

- macht `ccclean.py` ausführbar;
- legt einen `ccclean`-Symlink im ersten beschreibbaren Verzeichnis deines `PATH`
  an (`/opt/homebrew/bin`, `/usr/local/bin` oder `~/.local/bin`) — ohne sudo;
- erstellt die Konfiguration `~/.config/ccclean/config.json` (Modus `600`).

> Falls `~/.local/bin` gewählt wird, aber nicht in deinem `PATH` liegt, füge dies
> zu `~/.zshrc` / `~/.bashrc` hinzu:
> `export PATH="$HOME/.local/bin:$PATH"`

### API-Schlüssel

Trage deine Schlüssel in `~/.config/ccclean/config.json` ein:

```json
{
  "deepseek_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

- **`anthropic_api_key`** — exakte Token-Zählung (der Standardmodus).
  Erhältlich unter <https://console.anthropic.com/> → API Keys.
- **`deepseek_api_key`** — Zusammenfassungen des entfernten Abschnitts.
  Erhältlich unter <https://platform.deepseek.com/> → API Keys.

Du kannst sie auch über Umgebungsvariablen setzen (die Vorrang haben):
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`.

Ohne Anthropic-Schlüssel greift es automatisch offline auf `tiktoken` zurück
(näherungsweise). Ohne DeepSeek-Schlüssel wird die Zusammenfassung übersprungen.

---

## Verwendung

```bash
ccclean                       # pick a session from the list + free 50k (default)
ccclean 30k                   # pick a session + free 30k
ccclean <session-id>          # a specific session + free the default amount
ccclean <session-id> 30k      # a specific session + free 30k
ccclean <session-id> --keep 200k     # keep roughly the last 200k tokens
ccclean <session-id> 50k --dry-run   # show the plan, change nothing
ccclean <session-id> 100k --fast     # fast offline counting (tiktoken)
```

Die Menge wird als Positionsargument (`30k`, `50000`, `1.5m`) oder als Flag
`--free` / `--keep` angegeben (das Flag gewinnt). Die Reihenfolge der Argumente
spielt keine Rolle. Die `session-id` kann abgekürzt werden (wie in der
Auswahlliste). Für die vollständige Liste der Flags: `ccclean -h`.

Wird keine Menge angegeben, verwendet es `default_free` aus
`~/.config/ccclean/config.json` (bei der Installation `50k`; der eingebaute
Fallback ohne Konfiguration ist `10k`) — ändere es dort, um deinen Standard ein
für alle Mal festzulegen.

Setze die Sitzung nach der Bereinigung fort:

```bash
claude --resume <session-id>
```

---

## Automatische Bereinigung (der Hook + `ccclaude`)

Damit du nicht von Hand bereinigen musst, gibt es einen automatischen Modus: Wenn
sich der Kontext füllt und Claude Code eine Komprimierung startet, fängt der Hook
sie ab und führt statt der verlustbehafteten Komprimierung `ccclean` aus,
woraufhin die Sitzung bereits entlastet neu startet.

`install.sh` richtet dies für dich ein:

- installiert den Wrapper-Befehl **`ccclaude`**;
- legt den Hook unter `~/.claude/hooks/ccclean-hook.sh` ab;
- registriert ihn in `~/.claude/settings.json` für das `PreCompact`-Ereignis, aber
  nur für **automatische** Komprimierung (manuelles `/compact` bleibt unangetastet
  — wenn du es selbst ausgeführt hast, dann wolltest du auch eine Komprimierung);
- aktiviert `autoCompactEnabled: true` (notwendig, damit der Hook von selbst
  auslöst);
- setzt `autoCompactWindow: 1000000` — hebt die Auto-Compact-Schwelle nahe an die
  reale Obergrenze des Modells (Claude Code berechnet die Schwelle als
  `window − ~33k`), damit „Kontextlimit erreicht“ nicht vorzeitig auslöst.

> So funktioniert es im Inneren von Claude Code (aus dem Reverse Engineering des
> Bundles): Die Sperre greift, wenn das `usage` der letzten Antwort ≥
> `auto-compact-window − output_reserve(≤20k) − 13k` ist. Zwei Hebel helfen also:
> das Fenster anheben (`autoCompactWindow`, erledigt install.sh) und den Zähler
> nach der Bereinigung senken (`usage_subtract`, erledigt ccclean).

**So verwendest du es:** Starte Claude Code über den Wrapper (in einem Terminal):

```bash
ccclaude --resume <session-id>      # instead of `claude --resume <session-id>`
```

Der Ablauf, wenn es voll wird:

1. Claude Code erreicht das Limit → startet Auto-Compact.
2. Der Hook `ccclean-hook.sh` markiert die Sitzung und beendet `claude`
   (Komprimierung abgebrochen).
3. Der `ccclaude`-Wrapper erkennt die Markierung → wartet ~2 s →
   `ccclean <id> --force` → startet neu und sendet sofort den Prompt:
   `claude --resume <id> "continue"`.

Die Schnittgröße pro Zyklus wird festgelegt (in dieser Prioritätsreihenfolge):

1. die Umgebungsvariable `CCCLEAN_FREE` (einmalig),
2. der Schlüssel `default_free` in `~/.config/ccclean/config.json` (dauerhaft),
3. der eingebaute Fallback `10k`.

```bash
CCCLEAN_FREE=300k ccclaude --resume <id>   # one-off, unload an overflowing session
```

```json
// ~/.config/ccclean/config.json — change the default once and for all
{ "default_free": "30k" }
```

**Einschränkungen:**

- Funktioniert **in einem Terminal**, nicht innerhalb von VS Code (der Hook
  beendet den `claude`-Prozess; VS Code hat ein anderes Prozessmodell).
- Wenn die Sitzung direkt an der Obergrenze liegt, holt ein kleiner Schnitt
  (`10k`) sie womöglich nicht in einem einzigen Zyklus aus dem Limit — erhöhe
  `CCCLEAN_FREE` für eine einmalige Entlastung.

### Proaktiver Modus (`clean_at`)

Damit du „Kontextlimit erreicht“ gar nicht erst erreichst, gibt es einen zweiten
Hook — auf dem `Stop`-Ereignis (nach jeder Antwort). Er liest das aktuelle `usage`
aus dem Transkript, und wenn es über der Schwelle **`clean_at`** liegt (ein
Schlüssel in `config.json`, z. B. `"940k"`), führt er denselben
Bereinigungszyklus (kill → `ccclean` → Neustart) vorzeitig aus — noch unterhalb
des Limits. So tritt die Sperre nie ein. Der Modus wird durch das Vorhandensein
von `clean_at` in der Konfiguration aktiviert.

### Automatisches Fortsetzen (`resume_prompt`)

Nach dem Neustart öffnet der Wrapper die Sitzung nicht nur — er **sendet sofort
einen Prompt hinein**, damit die Arbeit ohne dein Zutun weitergeht:

```bash
claude --resume <id> "continue"     # claude sends the prompt right at startup
```

Der Text wird durch den Schlüssel **`resume_prompt`** in `config.json` festgelegt
(Standard `"continue"`):

```json
{ "resume_prompt": "continue from where you left off" }
```

Eine leere Zeichenkette (`""`) → einfach fortsetzen, ohne automatisches Senden.

### Hook-Sicherheit

Die Hooks `Stop` / `PreCompact` **beenden den `claude`-Prozess**, daher greifen
sie nur in Sitzungen, die über den `ccclaude`-Wrapper gestartet wurden (der
`CCCLEAN_WRAPPED=1` setzt). In gewöhnlichen Sitzungen (`claude`, VS Code) sind die
Hooks wirkungslos und rühren nichts an.

---

## Funktionsweise

1. Findet die Sitzungsdatei (per ID oder über die interaktive Auswahl).
2. Rekonstruiert den **aktiven Zweig** des Dialogs — die Kette von der letzten
   Nachricht entlang `parentUuid` zurück bis zur Wurzel (genau das wird in den
   Kontext geladen).
3. Zählt die Token (Anthropic-API — exakt; `--fast` — tiktoken).
4. Bestimmt den Schnittpunkt für die angeforderte Menge und richtet ihn an einer
   Benutzernachrichtsgrenze aus (es schneidet nicht weniger als angefordert).
5. Fragt nach Bestätigung (und mit `--summary` eine kurze Zusammenfassung des
   entfernten Abschnitts via DeepSeek).
6. Erstellt ein Backup `*.jsonl.bak-<date>`, löscht die alten Nachrichten und
   verknüpft die Wurzel neu.
7. Überprüft die Integrität des Ergebnisses.

---

## Für KI-Agenten

Falls ein Agent (statt eines Menschen) dieses Tool ausführt, beachte:

- **Nicht-interaktiver Modus:** `-y` (keine Bestätigungen), `--fast` (kein
  Netzwerk, Offline-Zählung). Die DeepSeek-Zusammenfassung ist standardmäßig AUS —
  aktiviere sie mit `--summary`. Du **musst** die Sitzung mit einer expliziten
  `session-id` angeben — ohne sie startet die interaktive Auswahl und blockiert.
  ```bash
  ccclean <session-id> 50k --fast -y
  ```
- **Vorschau ohne Änderungen:** `--dry-run` — gibt den Plan aus („gibt ≈ X frei“,
  „behält ≈ Y“) und beendet sich, ohne etwas anzurühren. Praktisch zum Abschätzen.
- **Garantie:** Es schneidet tatsächlich **nicht weniger** als die angeforderte
  Menge ab; die Zahl bei „gibt ≈ frei“ in der Ausgabe entspricht exakt der realen
  Löschung.
- **Nur der aktive Zweig:** Das Tool rührt nur die aktuelle lineare Kette des
  Dialogs an. Der System-Prompt, die Tool-Schemata, MCP und `CLAUDE.md` gehören
  zum Kontext, werden aber durch das Beschneiden **nicht** entfernt (sie stehen
  nicht in der `.jsonl`).
- **Standardmäßig sicher:** Es wird stets ein Backup erstellt (mit `--no-backup`
  deaktivierbar). Zum Zurücksetzen kopiere `*.jsonl.bak-*` über `*.jsonl`.
- ⚠️ **Nur ausführen, wenn die Zielsitzung GESCHLOSSEN ist:** Ein offener Prozess
  von Claude Code schreibt die Datei aus dem Speicher neu und überschreibt deine
  Änderungen. Das Tool prüft dies via `lsof` und **verweigert** das Beschneiden
  einer offenen Sitzung (mit `--force` erzwingbar).

---

## Vorbehalte

- **Nur ausführen, wenn die zu bereinigende Sitzung geschlossen ist** (geprüft via
  `lsof`; das Tool verweigert das Beschneiden einer offenen Sitzung, mit `--force`
  erzwingbar).
- Vor jedem Schnitt wird automatisch ein Backup neben der Sitzungsdatei angelegt.
- Die Token-Zählung via `tiktoken` (`--fast`) ist näherungsweise (sie zählt bei
  kyrillischer Schrift zu niedrig); für exakte Zahlen verwende den Standardmodus
  (Anthropic-API).

---

## Lizenz

[MIT](LICENSE) © [Glym143](https://github.com/Glym143)
