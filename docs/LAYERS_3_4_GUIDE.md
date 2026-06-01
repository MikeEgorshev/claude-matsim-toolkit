# Слои 3 и 4 — глубокий разбор и руководство по расширению

Подробное описание слоёв **«Действия» (`tools/`)** и **«MCP-обёртка» (`mcp-servers/matsim-tools/`)**:
что там уже есть, как оно устроено, какие были подводные камни при разработке и как
правильно добавлять новые инструменты. Это расширение `CONTRIBUTING.md` — если
тот документ говорит «куда смотреть», этот — «как именно сделать».

---

## Слой 3 — Действия (`tools/`)

### Что это и чем не является

Слой 3 — это набор **независимых CLI-скриптов**, каждый из которых решает одну
задачу и возвращает компактный JSON на stdout. Они работают и без MCP-обёртки —
через обычный `python tools/...py`. MCP слой 4 их **оборачивает**, но не заменяет.

**Базовые принципы (нарушать только осознанно):**

| Принцип | Зачем |
|---------|-------|
| Только stdlib (`xml.etree`, `csv`, `json`, `gzip`, `pathlib`, `subprocess`, `argparse`) | Никаких `pip install` для пользователя CLI. Тулкит должен «просто работать». |
| Stdout — JSON, ничего лишнего | Чтобы MCP/агент мог парсить вывод напрямую. Прогресс/лог — в stderr или файл. |
| Изменяющие инструменты обязаны: `--dry-run`, `--output` отдельный от входного, `--force` для перезаписи | Случайно затереть `network.xml` пользователю — катастрофа. |
| Большие XML — потоково через `iterparse`, поддерживать `.gz` | Сети/планы бывают на сотни МБ. Не валим память. |
| Возвращаемые dict'ы — **через общую функцию**, не только через `main()` | Чтобы MCP-сервер мог импортировать ту же логику без subprocess. |

### Текущие инструменты

#### `tools/matsim_summary.py` — сводка network/plans

**Что делает:** потоково парсит `network.xml(.gz)` или `plans.xml(.gz)`, выдаёт
агрегаты: число узлов/звеньев, диапазоны `freespeed_ms` и `capacity_vph`,
распределение типов дорог; для планов — размер популяции, типы активностей, моды.

**Контракт CLI:**
```
python matsim_summary.py --network <path[.gz]> [--plans <path[.gz]>] [--pretty]
```

**Чувствительные точки в коде:**
- `summarize_network()` использует `ET.iterparse` + `elem.clear()` после обработки
  — это даёт стриминг и константную память. Не меняй на `ET.parse(...).getroot()`
  для больших сетей.
- Поддержка `.gz`: `gzip.open(path, "rb")` прозрачно через `_open_maybe_gzip()`.
  Парсер байтов, не текста — namespace снимается через `tag.split("}")[-1]`.
- **Предупреждение `freespeed > 50 м/с`** (≈180 км/ч). Это эвристика на классическую
  ошибку «забыли поделить на 3.6». Порог не трогай не подумав — выше 50 м/с реальных
  лимитов в РК нет.

**Импортируемые функции для MCP:** `summarize_network(Path)`, `summarize_plans(Path)`.

#### `tools/matsim_metrics.py` — метрики прогона

**Что делает:** парсит штатные `;`-разделённые CSV MATSim в папке `output/`:
`scorestats.csv`, `modestats.csv`, `traveldistancestats.csv`. Возвращает: число
итераций, эволюция score (начало/конец/дельта), modal split (начальный и финальный),
средняя дальность поездки.

**Контракт CLI:**
```
python matsim_metrics.py <output_dir> [--pretty]
```

**Чувствительные точки:**
- Колонка «iteration» в разных файлах — то `iteration`, то `ITERATION`. Поиск
  регистронезависимый через `_iter_key()`.
- В `scorestats.csv` нужная колонка — `avg_executed` (новый формат) или `executed`
  (старый). Падать при отсутствии нельзя — кладём в `warnings` и продолжаем.
- Для `traveldistancestats.csv` предпочитаем колонку со словом `trip` в названии,
  иначе первую доступную.

**Импортируемая функция для MCP:** `collect_metrics(Path) -> dict`.

#### `tools/matsim_run.py` — запуск симуляции

**Что делает:** запускает `java -cp <jar> <main-class> [config] [--config:...
переопределения]` через subprocess; stdout MATSim уходит в лог-файл, а инструмент
печатает компактный JSON c результатом (status, exit_code, duration_s, log_file,
опц. метрики через `--summarize`).

**Контракт CLI:**
```
python matsim_run.py --jar <jar> [--main-class <fqcn>] [--config <path>]
    [--iterations N] [--output <dir>] [--network <file>] [--threads N]
    [--cwd <dir>] [--timeout SEC] [--summarize] [--dry-run] [--pretty]
```

**Подводные камни (нашли в ходе тестов — не наступай заново):**

1. **Относительные пути и `--cwd`.** MATSim резолвит `controler.outputDirectory`
   относительно своей рабочей папки запуска. Если `--output runs/X` + `--cwd PROJ`,
   реальный путь — `PROJ/runs/X`. Помощник `_against_cwd()` делает это явно;
   `_resolve_output_dir()` использует его при поиске метрик.

2. **Лог НЕ должен лежать внутри `output/`.** MATSim удаляет/пересоздаёт `output/`
   при старте; на Windows открытый хэндл лога внутри ломает удаление → повторный
   прогон падает. Поэтому лог пишется в **родительскую** папку с именем по имени
   output: `<output_parent>/<output_name>_run_<timestamp>.log`.

3. **`--extra` со значением, начинающимся на `--`, ломает argparse** (`expected one
   argument`). Поэтому самые частые `--config:` оверрайды вынесены в штатные флаги
   (`--iterations`, `--output`, `--network`). Если нужен ещё один — добавь штатный
   флаг, не лезь через `--extra` с кавычками.

4. **Сборка JVM-команды** — в `build_command(args)`. Все MATSim-оверрайды идут
   через `--config:module.param=value` (точечная нотация). Сам `config.xml` не
   меняется — это важно: эксперимент воспроизводим, исходник не трогается.

**Импортируемые элементы для MCP:** `build_command(args)` (для тестов сборки).
Сам запуск MCP делает через subprocess CLI — не дублируем процесс-лаунчер.

#### `tools/matsim_modify.py` — изменение network.xml

**Что делает:** единственный инструмент, который **меняет** модель — поэтому
максимально осторожный. Операции комбинируются на `--links`: `--set-capacity`,
`--set-freespeed` (м/с), `--set-freespeed-kmh` (÷3.6), `--set-lanes` (→ `permlanes`),
`--remove-modes`, `--close-link` (= убрать `car`). Возвращает JSON со списком
изменений `старое → новое` и предупреждениями.

**Контракт CLI:**
```
python matsim_modify.py --network <in> --output <out_copy> --links <ids>
    [--set-capacity X] [--set-freespeed X] [--set-freespeed-kmh X] [--set-lanes N]
    [--remove-modes MODE[,..]] [--close-link] [--dry-run] [--force] [--pretty]
```

**Защитные механизмы (порядок проверок имеет значение):**

1. **`validate_ops()` — параметры без обращения к файлу.** Capacity > 0, freespeed
   > 0, нельзя оба `set-freespeed` и `set-freespeed-kmh` одновременно, lanes >= 1.
   Возвращает список ошибок → если есть, статус `invalid`, файл не открывается.
2. **Защита оригинала.** Если `output == network` и нет `--force` → статус `error`.
3. **Проверка существования link id** в сети — если каких-то нет, статус `error` со
   списком отсутствующих, файл не пишется.
4. **DOCTYPE сохраняется** — иначе MATSim ругается. Извлекается из исходного файла
   регуляркой `<!DOCTYPE[^>]*>`, добавляется обратно при записи.
5. **Запись только если не `--dry-run`** — в копию (`--output`).

**Семантика `--close-link`:** убирает `car` из атрибута `modes`. Если звено было
только car — `modes` становится пустым, инструмент **предупреждает**: агенты не
смогут использовать это звено, могут быть проблемы маршрутизации. Альтернатива
(в очереди) — `NetworkChangeEvents` для временных закрытий.

**Импортируемая функция для MCP:** `apply_modifications(SimpleNamespace) -> dict`
(аргументы — те же что у CLI, через `types.SimpleNamespace`).

### Как добавить новый CLI-инструмент

**Шаги:**

1. **Имя:** `tools/matsim_<глагол>.py` (например, `matsim_validate.py`).
2. **Заголовок:** docstring сверху на 3-6 строк — что делает, контракт CLI,
   зависимости (должно быть «только stdlib»).
3. **Разделить логику и CLI:** одна основная функция `def do_work(args) -> dict`,
   `main(argv=None) -> int` только парсит argparse и печатает JSON.
4. **Контракт вывода:** `{"status": "ok"|"error"|..., ...}`. Ошибки — список в
   `errors`. Предупреждения — в `warnings`.
5. **Если меняет файл — реализовать:** `--dry-run`, отдельный `--output`, `--force`
   для перезаписи, валидация ДО открытия файлов на запись.
6. **Поддерживать `.gz` на чтении и записи**, если работаешь с network/plans/events.

**Шаблон:**

```python
#!/usr/bin/env python3
"""matsim_<name>.py — что делает в одну строку.

Использование:
    python matsim_<name>.py --input X [--pretty]

Зависимости: только стандартная библиотека.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path


def do_work(args) -> dict:
    result = {"status": "ok", "warnings": [], "errors": []}
    # ... логика ...
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="...")
    p.add_argument("--input", required=True)
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args(argv)
    result = do_work(args)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
```

**Тестирование на реальных данных (минимум):**

```bash
python tools/matsim_<name>.py --input <реальный_файл_Shamalgan> --pretty
# и потом dogfood — пропустить результат через matsim_summary если применимо
```

**Проверка совместимости с MCP:** если функция `do_work` принимает чистые типы
(str, int, float, Path), её легко обернуть `@mcp.tool()` в server.py через
`SimpleNamespace`. Если принимает `argparse.Namespace` со специфичными атрибутами —
вытащи ядро в чистую функцию.

---

## Слой 4 — MCP-обёртка (`mcp-servers/matsim-tools/`)

### Что это и чем не является

Слой 4 — **тонкая обёртка** над `tools/`, которая делает инструменты нативно
доступными агенту через Model Context Protocol. **Доменная логика не дублируется**:
MCP-функции либо импортируют из `tools/` и вызывают, либо запускают CLI как
subprocess (для процесс-лаунчеров типа `run_simulation`).

**Базовые принципы:**

| Принцип | Зачем |
|---------|-------|
| Никакой бизнес-логики в `server.py` — только маршалинг параметров | Двойная поддержка убивает | 
| Type hints у `@mcp.tool()` — простые (`str`, `int`, `float`, `bool`, `X \| None`) | FastMCP по ним строит JSON-схему для агента |
| Docstring — то что видит агент при выборе инструмента | Пиши осмысленно: что делает, что возвращает, когда уместно |
| Длинные/блокирующие операции — async pattern (launch-and-poll) | MCP-хост имеет таймаут на блокирующий вызов |
| Зависимости (`mcp`) только в этом слое | `tools/` остаётся stdlib и работает без MCP |

### Текущие 6 инструментов

| Инструмент | Где логика | Тип |
|------------|------------|-----|
| `get_network_summary` | `tools/matsim_summary.py::summarize_network/summarize_plans` (импорт) | read-only, sync |
| `get_simulation_metrics` | `tools/matsim_metrics.py::collect_metrics` (импорт) | read-only, sync |
| `modify_network` | `tools/matsim_modify.py::apply_modifications` (импорт) | mutator, sync (быстро) |
| `run_simulation` | `tools/matsim_run.py` (subprocess) | блокирующий — только dry-run/smoke |
| `start_simulation` | `tools/matsim_run.py` (Popen в фоне) | async launch |
| `get_run_status` | реестр `~/.matsim_runs/` (чтение файлов) | async poll |

### Sync-паттерн (read-only и modify)

Простейший случай. Импортируешь функцию из `tools/`, оборачиваешь `@mcp.tool()`,
маршалишь параметры. Modify-функция ожидает `argparse.Namespace` — конструируем
`SimpleNamespace` со всеми её атрибутами.

```python
from matsim_modify import apply_modifications

@mcp.tool()
def modify_network(
    network: str, output: str, links: str,
    set_capacity: float | None = None, ...,
    dry_run: bool = False,
) -> dict:
    """Типизированно изменить network.xml с валидацией ДО записи. ..."""
    args = SimpleNamespace(
        network=network, output=output, links=links,
        set_capacity=set_capacity, ..., dry_run=dry_run,
    )
    return apply_modifications(args)
```

**Зачем `SimpleNamespace`:** функция писалась под CLI и привыкла читать `args.X`.
`SimpleNamespace` даёт тот же интерфейс без переписывания. Альтернатива — заставить
функцию принимать `dict` или kwargs, но это ломает CLI-совместимость.

### Subprocess-паттерн (sync, для процесс-лаунчеров)

`run_simulation` запускает `tools/matsim_run.py` как subprocess, не импортирует.
Почему: `matsim_run.py` сам по себе уже субпроцесс-лаунчер MATSim. Дублировать
логику запуска в server.py — копипаста.

```python
proc = subprocess.run(
    cmd, capture_output=True, text=True, encoding="utf-8",
    errors="replace", env=env
)
return json.loads(proc.stdout)
```

Команда собирается общим хелпером `_matsim_run_cmd()`, который используется и
sync, и async-путём — единый источник правды для argv.

### Async-паттерн (launch-and-poll) — для длинных прогонов

**Проблема:** реальный прогон MATSim занимает минуты. Sync MCP-tool блокирует
вызов на всё это время → хост-таймаут → выглядит как зависание.

**Решение:** разделить на два инструмента — запуск и опрос.

#### `start_simulation` — мгновенный запуск в фоне

Логика:

1. Сгенерировать `run_id` = `YYYYMMDD_HHMMSS_<hex6>`.
2. Создать папку реестра (если её нет): `~/.matsim_runs/`.
3. Открыть файлы для stdout и stderr дочернего процесса: `<run_id>.result.json`
   и `<run_id>.err`.
4. Запустить `subprocess.Popen` с `creationflags=DETACHED_PROCESS` на Windows
   (на Unix — 0), `cwd=cwd`, перенаправлением в эти файлы. **`Popen`, не `run`** —
   возвращается мгновенно, не ждёт завершения.
5. Записать `<run_id>.meta.json` с командой, pid, started_at, путями.
6. Вернуть `{run_id, status: "running", started_at, message}`.

**Важно про файлы:** открываем `out_fh`, `err_fh`, передаём в Popen, **сразу
закрываем** свои дескрипторы. Дочерний процесс держит свой через `creationflags`.

#### `get_run_status` — кросс-платформенная проверка завершения

**Принцип определения завершения:** `matsim_run.py` печатает **ровно один** JSON-объект на stdout в
самом конце. Пока работает — stdout пуст. Значит:

| Состояние `<run_id>.result.json` | Вывод | Почему |
|----------------------------------|-------|--------|
| Пуст | `status: "running"` + `elapsed_s` | matsim_run ещё не закончил |
| Не пуст и распарсился как JSON | `status: result.status` + `elapsed_s` + полные метрики | завершён |
| Не пуст и НЕ JSON | `status: "error"` + tail stdout и stderr | редкий случай: launcher упал криво |
| Пуст, но в `.err` есть `Traceback` | `status: "error"` + stderr tail | python-уровень упал до вывода |

**Почему не проверяем pid?** На Windows `os.kill(pid, 0)` фактически терминирует
процесс — несовместимо. Использовать `psutil` — лишняя зависимость. А проверка
«есть валидный JSON?» работает везде одинаково и совпадает с реальным состоянием
(matsim_run пишет JSON только в самом конце).

**Файлы реестра живут в `~/.matsim_runs/`** — не в проекте. Тогда `get_run_status`
находит run по id независимо от того, в каком cwd сейчас агент.

### Как добавить новый MCP-инструмент

#### Случай 1 — обычный sync (read-only или быстрый mutator)

1. Логику положить в `tools/matsim_<X>.py` как чистую функцию (см. слой 3).
2. В `server.py` импортировать функцию.
3. Обернуть `@mcp.tool()` с понятным docstring.
4. Тип-хинты — простые. `X | None = None` для опциональных.

```python
from matsim_<x> import do_work

@mcp.tool()
def my_new_tool(input_path: str, threshold: float | None = None) -> dict:
    """Что делает в 1-3 строках. Что возвращает.

    Docstring видит агент — пиши осмысленно. Сюда же — когда уместно вызывать,
    каких ловушек избегать (например, что параметр в каких единицах).
    """
    args = SimpleNamespace(input=input_path, threshold=threshold)
    return do_work(args)
```

#### Случай 2 — async (длинная операция)

Если задача может длиться больше ~30 секунд (запуск симуляции, тяжёлый анализ
events.xml.gz, перестройка большой сети) — async-pattern обязателен.

1. Под капотом — CLI-инструмент в `tools/`, который сам по себе работает как
   фоновый процесс и в КОНЦЕ печатает один JSON на stdout.
2. В `server.py` добавить **пару**: `start_<X>` (запуск через Popen, мгновенный
   возврат `run_id`) + `get_<X>_status` (чтение результата по id).
3. Использовать тот же реестр `~/.matsim_runs/` или завести параллельный
   (`~/.matsim_<task>/`) если структура другая.
4. Документировать в docstring: «реальные/длинные — через start+poll, не через
   sync-вариант».

### Тестирование MCP-инструментов

Файл: `mcp-servers/matsim-tools/test_server.py`.

**Что покрывать:**

| Тип теста | Как |
|-----------|-----|
| Регистрация | `await server.mcp.list_tools()` → проверить что имена в наборе |
| Read-only | вызов функции напрямую (декоратор `@mcp.tool()` не ломает прямой вызов) на реальных файлах |
| Mutator | dry_run=True + проверка что результат содержит ожидаемые поля |
| Валидация | передать заведомо неверный параметр, проверить `status == "invalid"` |
| Sync subprocess | dry_run=True + проверка что в `command[]` есть нужный класс |
| Async (start+poll) | реальный короткий прогон 1-2 итераций + опрос до `completed` |

Тесты вызывают **функции напрямую**, не через MCP-протокол. Это покрывает наши
определения инструментов. Сам MCP-транспорт (stdio) — это FastMCP, он
протестирован апстримом.

**Живая проверка через MCP-протокол** (отдельно от test_server):

1. После добавления инструмента → перезапустить Claude Code (MCP-серверы грузятся
   при старте сессии).
2. В новой сессии агент увидит `mcp__matsim-tools__<name>`.
3. Попросить его словами: «вызови …». Если ответил — значит JSON-схема и
   маршалинг работают через сам протокол.

### Регистрация и подключение

**Глобальная регистрация (user-scope)** — один раз:

```bash
claude mcp remove matsim-tools  # если была локальная регистрация
claude mcp add --scope user matsim-tools -- python "<полный путь к server.py>"
claude mcp list                  # должно быть ✓ Connected
```

**Где живёт регистрация:** `~/.claude.json`, секция `mcpServers`.

**Если health check падает:**
- Проверь что путь к `server.py` существует (в т.ч. пробелы в «Claude Projects» —
  путь должен быть в кавычках при `claude mcp add`).
- Проверь что пакет `mcp` стоит: `python -c "from mcp.server.fastmcp import FastMCP"`.
- Проверь что импорты в `server.py` работают: запусти `python server.py` руками
  (сервер запустится в режиме stdio, можно прервать Ctrl+C — главное чтобы не
  упал на импорте).

**После любого изменения server.py — нужен рестарт Claude Code,** чтобы агент
увидел обновлённые инструменты. Это ограничение MCP-протокола, не наше.

---

## Связь между слоями (правило DRY)

**Где должна жить логика — в `tools/` или в `server.py`?**

В `tools/`. **Всегда.** `server.py` — только маршалинг.

Если соблазн добавить «маленькую логику прямо в `@mcp.tool()`» — это значит:
1. эту же логику нельзя будет вызвать через CLI;
2. её нельзя протестировать без MCP-окружения;
3. она дублируется когда понадобится в другом инструменте.

**Признак правильного разделения:** `server.py` содержит почти только
`@mcp.tool()` декораторы + 5-10 строк маршалинга в каждой функции. Большие тела
функций в `server.py` — звоночек что логика просочилась не туда.

**Исключение:** код обвязки самого async-паттерна (генерация run_id, работа с
реестром, парсинг результата) — он MCP-специфичный и живёт в `server.py`
обоснованно. Если он начнёт расти — выноси в отдельный модуль `_async_runner.py`
рядом с server.py.

---

## Чеклист перед коммитом изменений в слои 3 / 4

- [ ] CLI-инструмент работает без MCP (`python tools/...py --help` + реальный прогон)
- [ ] Импортируемая функция оформлена отдельно от `main()` (не argparse-only)
- [ ] Если меняет файл — есть `--dry-run`, отдельный `--output`, `--force`
- [ ] MCP-обёртка не дублирует логику (импорт из `tools/` или subprocess)
- [ ] Type hints у `@mcp.tool()` — простые
- [ ] Docstring у `@mcp.tool()` понятен агенту (что, зачем, когда уместно)
- [ ] Если операция длинная — есть `start_*` / `get_*_status` пара
- [ ] Кейс добавлен в `tests/test_hooks.py` или `mcp-servers/.../test_server.py`
- [ ] Прогнан на реальном Shamalgan-сценарии хотя бы один раз
- [ ] `tools/README.md` или `mcp-servers/matsim-tools/README.md` обновлён
- [ ] `PROGRESS.md` обновлён (журнал + статус + проверки)
