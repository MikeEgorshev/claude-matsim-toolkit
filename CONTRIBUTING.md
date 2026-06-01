# CONTRIBUTING — как редактировать и дополнять toolkit

Этот документ описывает как правильно вносить изменения в `claude-matsim-toolkit`:
добавить правило в скилл, проверку в hook, инструмент в `tools/` или в MCP-сервер.
Цель — чтобы изменения не ломали уже работающие слои и оставались проверяемыми.

Документ адресован одновременно человеку и AI-агенту (Claude в сессии). Если
работаешь через агента — просто говори словами что нужно, агент сам найдёт нужный
файл; этот документ — карта местности.

---

## Карта проекта (5 секунд)

```
claude-matsim-toolkit/
├── skills/transport-modeling/      [1] ЗНАНИЯ          — правила, источники
├── hooks/                          [2] БЕЗОПАСНОСТЬ    — валидация перед записью
├── tools/                          [3] ДЕЙСТВИЯ (CLI)  — чистый stdlib Python
├── mcp-servers/matsim-tools/       [4] MCP-ОБЁРТКА     — FastMCP, тонкая
├── docs/ARCHITECTURE.md            план-синтез на 4 слоя
├── PROGRESS.md                     живой отчёт (обновлять при каждой фиче)
├── tests/                          hook-тесты
├── examples/                       примеры использования
└── install/                        install.ps1 / install.sh
```

Подробнее — `docs/ARCHITECTURE.md` и `README.md`.

---

## Принципы (нарушать с осторожностью)

1. **Сначала проверка на реальных данных, потом коммит.** Тест на заглушке ≠ тест.
   Все слои в репо доказали что работают на реальном Shamalgan-сценарии — не теряй
   эту планку.
2. **`tools/` — на чистом stdlib.** Никаких `pip install` для CLI-слоя. Зависимости
   (`mcp`) живут только в MCP-обёртке.
3. **Агент не парсит сырой XML/CSV.** Любой инструмент возвращает компактный JSON.
4. **Contract-first перед записью.** Изменяющие операции валидируют параметры **до**
   касания файла (`matsim_modify.py` — образец).
5. **Не выдумывать значения.** Если правила нет в скилле — лучше честно сказать
   «не покрыто, см. источник X», чем сочинить.
6. **Длинные операции — async.** Реальные прогоны через `start_simulation` /
   `get_run_status`, не блокирующий `run_simulation`.

---

## Git-workflow

- Фичевая работа — в ветке `feature/<short-name>` от `main`.
- Влитие в `main` через `git merge --no-ff` с осмысленным сообщением (так история
  показывает «фичу», а не россыпь коммитов).
- После merge — удалить ветку локально и на `origin`.
- Обновлять `PROGRESS.md` в том же коммите что добавляет фичу.

```bash
git checkout -b feature/whatever-it-is
# ... работа + тесты ...
git add -A && git commit -m "Что и зачем"
git push -u origin feature/whatever-it-is
# когда готово к слиянию:
git checkout main
git merge --no-ff feature/whatever-it-is -m "Merge ..."
git push origin main
git branch -d feature/whatever-it-is
git push origin --delete feature/whatever-it-is
```

---

## Слой 1 — добавить/исправить правило в скилле

**Файлы:**
- `skills/transport-modeling/SKILL.md` — критические правила (всегда в контексте агента)
- `skills/transport-modeling/references/rules.md` — полный свод правил (~60)
- `skills/transport-modeling/references/sources.md` — карта тема → глава источника

**Правило — это:**

```markdown
| N5 | Краткая формулировка правила. | [SP] табл. 5 | Высокая |
```

`N5` = id (буква категории + порядковый номер). Категории сейчас: A (алгоритм),
Q (QSim), S (scoring), C (калибровка), R (replanning), N (сеть), P (PT), T (теория
потока), K (ПДД РК), D (нормы СП РК). Если правило критичное (нужно знать в любом
MATSim-вопросе) — продублируй краткую версию в `SKILL.md`.

**Источники:** `[M]` MATSim Book, `[G]` Горев, `[RK]` ПДД РК, `[SP]` СП РК. Если ссылаешься
на новый раздел — добавь запись в `references/sources.md`.

**Если глубокая выжимка нужна:** положи `.md` в `references/excerpts/`. Эта папка в
`.gitignore` (там копирайтное содержимое); агент её читает локально.

**Чек:** скилл подхватывается автоматически при старте сессии Claude Code. Чтобы
проверить эффект — открой новую сессию и задай вопрос, провоцирующий новое правило.

---

## Слой 2 — добавить проверку в hook

**Файл:** `hooks/validate_matsim.py`

Каждый валидатор — функция, принимающая полный текст файла + фрагмент правки,
возвращающая список ошибок (строк). Регистрируется в словаре `VALIDATORS` по
паттерну имени файла (например, `config.xml`, `network*.xml`).

**Шаблон новой проверки:**

```python
def validate_transit_schedule(content: str, edit_snippet: str) -> list[str]:
    errors = []
    # пример: проверить что есть awaitDeparture=true на всех stop'ах (правило P5)
    if 'awaitDeparture="false"' in content:
        errors.append('правило P5: awaitDeparture должен быть true для стабильности расписания')
    return errors

VALIDATORS["transitSchedule"] = validate_transit_schedule
```

**Что должно быть в проверке:**
- Срабатывание **только** на нужный тип файла (имя/контент).
- Текст ошибки **с номером правила** (`[правило Q1]`) — агент тогда сразу знает контекст.
- Никаких ложных срабатываний на не-MATSim файлы — пропускай молча.

**Тестирование:**

1. Добавь fixture в `hooks/test-fixtures/` (bad_*.xml и good_*.xml).
2. Добавь кейс в `tests/test_hooks.py` через `assert_blocked` / `assert_passed`.
3. `python tests/test_hooks.py` → должно быть N/N passed.

---

## Слой 3 — добавить CLI-инструмент в `tools/`

**Файл:** новый `tools/matsim_<name>.py`.

**Контракт:**
- Argparse, `--pretty` для отступов, JSON на stdout, ненулевой код при ошибке.
- Только stdlib (xml.etree, csv, json, gzip, pathlib, subprocess, argparse).
- Если изменяет модель — обязательно `--dry-run` и запись только в `--output`,
  отдельный от входного (`--force` для перезаписи).

**Шаблон:**

```python
#!/usr/bin/env python3
"""matsim_<name>.py — описание в одну строку."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

def do_work(args) -> dict:
    # ...
    return {"status": "ok", "...": ...}

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

**Тестирование:** прогоняй на реальном Shamalgan-сценарии (см. README — пути к
выходам/планам/сети). Если результат разумный — добавь короткий блок в `tools/README.md`.

**Reuse-правило:** общую логику оформляй как функцию (не только argparse), чтобы её
мог импортировать MCP-сервер. Образцы: `collect_metrics`, `summarize_network`,
`apply_modifications`, `_matsim_run_cmd`.

---

## Слой 4 — добавить MCP-инструмент в `mcp-servers/matsim-tools/server.py`

**Шаблон:**

```python
@mcp.tool()
def my_new_tool(arg1: str, arg2: int | None = None) -> dict:
    """Что делает (1-3 строки). Что возвращает.

    Это docstring видит агент при выборе инструмента — пиши осмысленно.
    """
    # Если в tools/ есть подходящая функция — зови её:
    return some_imported_function(arg1, arg2)
```

**Параметры:** type hints должны быть простыми (`str`, `int`, `float`, `bool`,
`X | None`). FastMCP по ним строит JSON-схему, видимую агенту.

**Длинные/блокирующие операции — НЕ в синхронном tool'е.** Дублируй паттерн
`start_simulation` / `get_run_status` (реестр `~/.matsim_runs/`, файл результата,
определение завершения по валидному JSON).

**Тестирование:**

1. Добавь кейс в `mcp-servers/matsim-tools/test_server.py` (вызывает функцию напрямую,
   как обычную; декоратор `@mcp.tool()` это не ломает).
2. `python test_server.py` → должно быть N/N.
3. Для живой проверки через сам MCP-протокол: рестарт Claude Code → агент в сессии
   увидит новый `mcp__matsim-tools__<name>` и сможет позвать.

**Регистрация уже глобальная** (user-scope), переустанавливать ничего не нужно.

---

## Документация — где что обновлять

| Изменение | Что обновить |
|-----------|--------------|
| Любая завершённая фича | `PROGRESS.md` (журнал + статус + проверки) |
| Новое правило в скилле | `references/rules.md`, при критичности — `SKILL.md` |
| Новый CLI-инструмент | `tools/README.md` (1-2 абзаца с примером) |
| Новый MCP-инструмент | `mcp-servers/matsim-tools/README.md` (строка в таблице) |
| Перестройка слоёв | `docs/ARCHITECTURE.md` |
| Опасные/новые шаги установки | `README.md`, `install/install.{ps1,sh}` |

**`PROGRESS.md` — это контракт с наблюдателем.** Статус фичи ставится только после
реальной проверки на данных. «Я написал» — не статус.

---

## Чеклист перед коммитом

- [ ] `python tests/test_hooks.py` → все passed
- [ ] `python mcp-servers/matsim-tools/test_server.py` → все passed (если трогал MCP)
- [ ] На реальных данных проверено (хотя бы один сценарий)
- [ ] `PROGRESS.md` обновлён (журнал + статус)
- [ ] Документация затронутого слоя обновлена
- [ ] Сообщение коммита: **что** изменилось + **зачем** (1-2 предложения)
- [ ] Если фича — отдельная ветка `feature/...`

---

## Если что-то сломалось

1. **Что в первую очередь:** прогнать оба тест-раннера (`tests/test_hooks.py`,
   `mcp-servers/matsim-tools/test_server.py`). Они покажут какой слой упал.
2. **Откат:** `git log` → найти последний рабочий коммит → `git revert <hash>` (не
   `reset --hard`, чтобы история сохранилась).
3. **Безопасный отладочный прогон:** `matsim_run.py --dry-run` — собирает команду,
   ничего не запускает.
4. **Если MCP не виден агенту:** `claude mcp list` → проверить `✓ Connected`.
   Регистрация в `~/.claude.json` (user-scope). Перерегистрация:
   `claude mcp remove matsim-tools && claude mcp add --scope user matsim-tools -- python "<полный путь к server.py>"`.

---

## Расширения, которые ждут своей очереди

(Из `PROGRESS.md` → «что дальше». Любой пункт — кандидат на отдельную ветку.)

- **NetworkChangeEvents** — временные закрытия звеньев по часам, отдельный
  XML-формат + CLI-генератор + MCP-инструмент.
- **Правка `plans.xml`** (спрос): change activity time/location, change mode for
  subset of agents.
- **Выбор «критического» звена по v/c ratio** — анализатор поверх метрик прогона
  для осмысленных сценариев типа «закрытия моста».
- **Парсер `events.xml.gz`** для модального расщепления и трасс агентов (события
  PersonEntersVehicle, LinkLeaveEvent и т.д.).
- **Скилл-евалы регулярно** — собирать новые тест-вопросы из реальной работы,
  гонять как итерации.

Когда возьмёшься за что-то из этого — обнови `PROGRESS.md`, заведи ветку, делай.
