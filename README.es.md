<div align="center">

# ccclean

**Un limpiador quirúrgico de contexto para sesiones de [Claude Code](https://docs.anthropic.com/en/docs/claude-code).**
Recorta los mensajes más antiguos de una conversación para liberar la ventana de contexto, con un paso de confirmación y un resumen opcional de lo que se elimina.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Platform: macOS | Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)

[English](README.md) · [Русский](README.ru.md) · [中文](README.zh-CN.md) · **Español** · [Deutsch](README.de.md)

</div>

---

Trabaja directamente sobre los archivos de sesión `.jsonl` que se encuentran en `~/.claude/projects/`.

## Contenido

- [Por qué ccclean](#por-qué-ccclean)
- [Características](#características)
- [Instalación](#instalación)
  - [Claves de API](#claves-de-api)
- [Uso](#uso)
- [Limpieza automática (el hook + `ccclaude`)](#limpieza-automática-el-hook--ccclaude)
  - [Modo proactivo (`clean_at`)](#modo-proactivo-clean_at)
  - [Continuación automática (`resume_prompt`)](#continuación-automática-resume_prompt)
  - [Seguridad del hook](#seguridad-del-hook)
- [Cómo funciona](#cómo-funciona)
- [Para agentes de IA](#para-agentes-de-ia)
- [Advertencias](#advertencias)
- [Licencia](#licencia)

---

## Por qué ccclean

Las sesiones largas de Claude Code llenan la ventana de contexto y el trabajo se
vuelve más difícil: el modelo alcanza su límite y la autocompactación se activa
en el momento equivocado, aplastándolo todo sin distinción. `ccclean` te da
**control preciso**: tú decides cuántos tokens liberar y exactamente qué
fragmento antiguo de la conversación descartar, después de ver primero un breve
resumen de él. La parte actual (reciente) de la conversación permanece intacta.

A diferencia del `/compact` integrado (que comprime el diálogo *entero* en un
resumen), `ccclean` simplemente **corta el inicio más antiguo** de la rama
activa, conservando los mensajes más recientes textualmente.

---

## Características

- ✂️ **Recorte preciso** — indicas una cantidad (`10k`, `50k`, `1.5m`) y la
  herramienta elimina mensajes antiguos desde el principio para liberar **al
  menos** la cantidad solicitada.
- 🔢 **Conteo honesto de tokens** — por defecto a través de la API oficial
  `count_tokens` de Anthropic (exacto), o sin conexión mediante `tiktoken`
  (`--fast`). Tiene en cuenta el texto, el `thinking`, las llamadas a
  herramientas y las **imágenes**.
- 📋 **Resumen de lo que se elimina (opcional)** — con el flag `--summary`, antes
  de borrar nada muestra un breve resumen del fragmento (vía DeepSeek) para que
  entiendas qué estás perdiendo. Desactivado por defecto.
- 📊 **Uso real de la ventana** — muestra el tamaño real del contexto a partir de
  los registros (`usage`), incluyendo el prompt del sistema, los esquemas de
  herramientas, MCP y `CLAUDE.md`.
- 🗂 **Selector interactivo de sesiones** — sin argumentos abre una lista de
  conversaciones (vía `fzf`, con búsqueda por título), para que no tengas que
  recordar el id.
- 🔓 **Levanta el bloqueo de «límite de contexto alcanzado»** — Claude Code
  determina el límite a partir del `usage` de la última respuesta, en lugar de
  volver a contar los mensajes recortados. Tras un corte, ccclean reduce ese
  contador en `usage_subtract` (por defecto `200k`, una clave en `config.json`),
  notablemente por debajo de lo que realmente se eliminó, de modo que la
  autocompactación no se dispare antes de la primera petición tras la limpieza.
  El contexto real sigue estando por debajo del límite, así que el servidor
  acepta la petición y Claude Code vuelve a calcular el contador a partir de los
  datos reales.
- 💾 **Seguridad** — una copia de seguridad automática antes de cada corte, una
  verificación de integridad, protección contra el borrado del diálogo completo
  y un reensamblado correcto de la raíz.

---

## Instalación

Necesitas **Python 3.8+** y `pip`. Todo lo demás (`tiktoken`, `anthropic`,
`fzf`) la herramienta lo instala por sí misma en la primera ejecución.

```bash
git clone https://github.com/Glym143/ccclean.git
cd ccclean
./install.sh
```

`install.sh`:

- hace ejecutable `ccclean.py`;
- crea un enlace simbólico `ccclean` en el primer directorio con permisos de
  escritura de tu `PATH` (`/opt/homebrew/bin`, `/usr/local/bin` o
  `~/.local/bin`), sin sudo;
- crea la configuración `~/.config/ccclean/config.json` (modo `600`).

> Si se elige `~/.local/bin` pero no está en tu `PATH`, añade esto a
> `~/.zshrc` / `~/.bashrc`:
> `export PATH="$HOME/.local/bin:$PATH"`

### Claves de API

Coloca tus claves en `~/.config/ccclean/config.json`:

```json
{
  "deepseek_api_key": "sk-...",
  "anthropic_api_key": "sk-ant-..."
}
```

- **`anthropic_api_key`** — conteo exacto de tokens (el modo por defecto).
  Consíguela en <https://console.anthropic.com/> → API Keys.
- **`deepseek_api_key`** — resúmenes del fragmento eliminado.
  Consíguela en <https://platform.deepseek.com/> → API Keys.

También puedes definirlas mediante variables de entorno (que tienen prioridad):
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`.

Sin una clave de Anthropic, recurre automáticamente a `tiktoken` sin conexión
(aproximado). Sin una clave de DeepSeek, se omite el resumen.

---

## Uso

```bash
ccclean                       # pick a session from the list + free 50k (default)
ccclean 30k                   # pick a session + free 30k
ccclean <session-id>          # a specific session + free the default amount
ccclean <session-id> 30k      # a specific session + free 30k
ccclean <session-id> --keep 200k     # keep roughly the last 200k tokens
ccclean <session-id> 50k --dry-run   # show the plan, change nothing
ccclean <session-id> 100k --fast     # fast offline counting (tiktoken)
```

La cantidad es posicional (`30k`, `50000`, `1.5m`) o un flag, `--free` / `--keep`
(el flag prevalece). El orden de los argumentos no importa. El `session-id` se
puede abreviar (como en la lista del selector). Para la lista completa de flags:
`ccclean -h`.

Si no se indica una cantidad, usa `default_free` de
`~/.config/ccclean/config.json` (instalado como `50k`; el valor de reserva
integrado si no hay configuración es `10k`); cámbialo ahí para fijar tu valor por
defecto de una vez por todas.

Tras la limpieza, reanuda la sesión:

```bash
claude --resume <session-id>
```

---

## Limpieza automática (el hook + `ccclaude`)

Para no tener que limpiar a mano, hay un modo automático: cuando el contexto se
llena y Claude Code lanza una compactación, el hook la intercepta y, en lugar de
una compresión con pérdidas, ejecuta `ccclean`, tras lo cual la sesión se
reinicia ya descargada.

`install.sh` lo configura por ti:

- instala el comando envoltorio **`ccclaude`**;
- coloca el hook en `~/.claude/hooks/ccclean-hook.sh`;
- lo registra en `~/.claude/settings.json` para el evento `PreCompact`, pero solo
  para la compactación **automática** (el `/compact` manual se deja en paz: si lo
  ejecutaste tú mismo, entonces querías una compactación);
- activa `autoCompactEnabled: true` (necesario para que el hook se dispare por sí
  solo);
- establece `autoCompactWindow: 1000000`, elevando el umbral de autocompactación
  cerca del techo real del modelo (Claude Code calcula el umbral como
  `window − ~33k`), de modo que «límite de contexto alcanzado» no se dispare
  prematuramente.

> Cómo funciona por dentro de Claude Code (a partir de la ingeniería inversa del
> bundle): el bloqueo se produce cuando el `usage` de la última respuesta es ≥
> `auto-compact-window − output_reserve(≤20k) − 13k`. Por eso hay dos palancas
> que ayudan: subir la ventana (`autoCompactWindow`, lo hace install.sh) y bajar
> el contador tras la limpieza (`usage_subtract`, lo hace ccclean).

**Cómo usarlo:** lanza Claude Code a través del envoltorio (en una terminal):

```bash
ccclaude --resume <session-id>      # instead of `claude --resume <session-id>`
```

El ciclo cuando se llena:

1. Claude Code alcanza el límite → lanza la autocompactación.
2. El hook `ccclean-hook.sh` marca la sesión y finaliza `claude` (compactación
   cancelada).
3. El envoltorio `ccclaude` ve la marca → espera ~2s → `ccclean <id> --force` →
   reinicia y envía de inmediato el prompt: `claude --resume <id> "continue"`.

El tamaño del corte por ciclo se define (en orden de prioridad):

1. la variable de entorno `CCCLEAN_FREE` (puntual),
2. la clave `default_free` en `~/.config/ccclean/config.json` (persistente),
3. el valor de reserva integrado `10k`.

```bash
CCCLEAN_FREE=300k ccclaude --resume <id>   # one-off, unload an overflowing session
```

```json
// ~/.config/ccclean/config.json — change the default once and for all
{ "default_free": "30k" }
```

**Limitaciones:**

- Funciona **en una terminal**, no dentro de VS Code (el hook finaliza el proceso
  `claude`; VS Code tiene un modelo de procesos distinto).
- Si la sesión está justo en el techo, un corte pequeño (`10k`) puede no sacarla
  del límite en un solo ciclo; aumenta `CCCLEAN_FREE` para una descarga puntual.

### Modo proactivo (`clean_at`)

Para que nunca llegues a «límite de contexto alcanzado», hay un segundo hook, en
el evento `Stop` (después de cada respuesta). Lee el `usage` actual del
transcript y, si está por encima del umbral **`clean_at`** (una clave en
`config.json`, p. ej. `"940k"`), ejecuta el mismo ciclo de limpieza
(kill → `ccclean` → reinicio) con antelación, mientras aún está por debajo del
límite. Así el bloqueo nunca ocurre. El modo se activa con la presencia de
`clean_at` en la configuración.

### Continuación automática (`resume_prompt`)

Tras el reinicio, el envoltorio no solo abre la sesión, sino que **le envía de
inmediato un prompt** para que el trabajo continúe sin tu intervención:

```bash
claude --resume <id> "continue"     # claude sends the prompt right at startup
```

El texto se define con la clave **`resume_prompt`** en `config.json` (por defecto
`"continue"`):

```json
{ "resume_prompt": "continue from where you left off" }
```

Una cadena vacía (`""`) → simplemente reanudar, sin envío automático.

### Seguridad del hook

Los hooks `Stop` / `PreCompact` **finalizan el proceso `claude`**, por lo que
solo actúan en sesiones lanzadas a través del envoltorio `ccclaude` (que define
`CCCLEAN_WRAPPED=1`). En sesiones normales (`claude`, VS Code) los hooks no hacen
nada y no tocan nada.

---

## Cómo funciona

1. Encuentra el archivo de sesión (por id o a través del selector interactivo).
2. Reconstruye la **rama activa** del diálogo: la cadena que va desde el último
   mensaje hacia atrás siguiendo `parentUuid` hasta la raíz (esto es exactamente
   lo que se carga en el contexto).
3. Cuenta los tokens (API de Anthropic — exacto; `--fast` — tiktoken).
4. Encuentra el punto de corte para la cantidad solicitada, alineándolo con el
   límite de un mensaje de usuario (corta no menos de lo solicitado).
5. Pide confirmación (y con `--summary`, un breve resumen del fragmento eliminado
   vía DeepSeek).
6. Crea una copia de seguridad `*.jsonl.bak-<date>`, elimina los mensajes
   antiguos y reensambla la raíz.
7. Verifica la integridad del resultado.

---

## Para agentes de IA

Si quien ejecuta esta herramienta es un agente (en lugar de un humano), ten en
cuenta:

- **Modo no interactivo:** `-y` (sin confirmaciones), `--fast` (sin red, conteo
  sin conexión). El resumen de DeepSeek está DESACTIVADO por defecto; actívalo
  con `--summary`. **Debes** especificar la sesión con un `session-id` explícito;
  sin él se lanza el selector interactivo y se queda colgado.
  ```bash
  ccclean <session-id> 50k --fast -y
  ```
- **Vista previa sin cambios:** `--dry-run` — imprime el plan («liberará ≈ X»,
  «conservará ≈ Y») y sale sin tocar nada. Útil para estimar.
- **Garantía:** realmente recorta **no menos** de la cantidad solicitada; el
  número «liberará ≈» de la salida coincide exactamente con el borrado real.
- **Solo la rama activa:** la herramienta toca únicamente la cadena lineal actual
  del diálogo. El prompt del sistema, los esquemas de herramientas, MCP y
  `CLAUDE.md` forman parte del contexto pero **no** se eliminan al recortar (no
  están en el `.jsonl`).
- **Seguro por defecto:** siempre se crea una copia de seguridad (desactívala con
  `--no-backup`). Para revertir, copia `*.jsonl.bak-*` sobre `*.jsonl`.
- ⚠️ **Ejecútala solo cuando la sesión objetivo esté CERRADA:** un proceso de
  Claude Code abierto reescribirá el archivo desde memoria y sobrescribirá tus
  cambios. La herramienta comprueba esto vía `lsof` y se **negará** a recortar
  una sesión abierta (fuérzalo con `--force`).

---

## Advertencias

- **Ejecútala solo cuando la sesión que se limpia esté cerrada** (se comprueba
  vía `lsof`; la herramienta se niega a recortar una sesión abierta, fuérzalo con
  `--force`).
- Se crea una copia de seguridad automáticamente junto al archivo de sesión antes
  de cada corte.
- El conteo de tokens vía `tiktoken` (`--fast`) es aproximado (subcuenta en
  cirílico); para números exactos usa el modo por defecto (API de Anthropic).

---

## Licencia

[MIT](LICENSE) © [Glym143](https://github.com/Glym143)
