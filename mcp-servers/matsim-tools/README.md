# MCP-сервер matsim-tools

Нативные MATSim-инструменты для LLM-агента через Model Context Protocol. Тонкая
обёртка над протестированными функциями из `../../tools/` — доменная логика не
дублируется.

## Инструменты

| Инструмент | Что делает |
|------------|------------|
| `get_network_summary` | сводка network.xml / plans.xml (вкл. .gz) → компактный JSON |
| `get_simulation_metrics` | метрики прогона из штатных CSV (score, modal split, дальность) |
| `modify_network` | типизированное изменение сети с валидацией и записью в копию |
| `run_simulation` | СИНХРОННЫЙ запуск (блокирует) — только dry-run и короткие smoke-прогоны |
| `start_simulation` | запуск В ФОНЕ, сразу возвращает `run_id` (не блокирует) |
| `get_run_status` | статус фонового прогона по `run_id`: `running` или финальные метрики |

После `*_simulation`/`modify_network` агент зовёт `get_simulation_metrics` и
`get_network_summary` — замкнутый цикл знания → действия → обратная связь.

### Реальные прогоны — через start/poll, не run_simulation

`run_simulation` блокирует вызов на всё время прогона, поэтому для реальных
(длинных) симуляций он упрётся в таймаут MCP. Правильный путь:

1. `start_simulation(...)` → мгновенно возвращает `run_id`;
2. периодически `get_run_status(run_id)` → пока `running`, потом финальные метрики.

Фоновый прогон пишет результат в `~/.matsim_runs/<run_id>.result.json`; завершение
определяется по наличию валидного JSON (кросс-платформенно, без pid-проверок).
`run_simulation` оставлен только для dry-run и smoke-прогонов на пару итераций.

## Установка зависимости

```bash
pip install -r requirements.txt
```
(Сами `tools/` зависимостей не требуют — только этот слой нуждается в пакете `mcp`.)

## Регистрация в Claude Code

Добавь сервер в конфиг MCP (`~/.claude.json` секция `mcpServers`, или через
`claude mcp add`). Пример:

```json
{
  "mcpServers": {
    "matsim-tools": {
      "command": "python",
      "args": ["C:/путь/к/claude-matsim-toolkit/mcp-servers/matsim-tools/server.py"]
    }
  }
}
```

Через CLI:
```bash
claude mcp add matsim-tools -- python /путь/к/claude-matsim-toolkit/mcp-servers/matsim-tools/server.py
```

После регистрации перезапусти Claude Code — инструменты появятся как `matsim-tools:*`.

## Тестирование

```bash
python test_server.py [путь_к_MATSim_проекту]
```
Проверяет регистрацию 6 инструментов и их работу на реальных данных: read-only и
modify dry-run быстрые, плюс реальный короткий async-прогон (start + poll, ~30 c).
Путь к проекту можно задать аргументом или переменной `MATSIM_PROJECT_DIR`.

## Замечания

- `run_simulation` блокирует на время прогона — используй только для dry-run и
  smoke-прогонов. Реальные/длинные прогоны: `start_simulation` + `get_run_status`
  (или CLI `tools/matsim_run.py` в фоне).
- CLI-инструменты в `tools/` остаются рабочими и независимыми — MCP их не заменяет,
  а оборачивает. Если MCP недоступен, всё работает через Bash.
