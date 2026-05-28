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
| `run_simulation` | запуск симуляции → компактный JSON (статус, метрики) |

После `run_simulation`/`modify_network` агент так же зовёт `get_simulation_metrics`
и `get_network_summary` — получается замкнутый цикл знания → действия → обратная связь.

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
Проверяет регистрацию 4 инструментов и их работу на реальных данных (без запуска
полной симуляции — только dry-run для run/modify). Путь к проекту можно задать
аргументом или переменной `MATSIM_PROJECT_DIR`.

## Замечания

- `run_simulation` блокирует на время прогона. Для длинных прогонов задавай `timeout`
  или малое число `iterations`; тяжёлые эксперименты удобнее гонять CLI-инструментом
  `tools/matsim_run.py` в фоне.
- CLI-инструменты в `tools/` остаются рабочими и независимыми — MCP их не заменяет,
  а оборачивает. Если MCP недоступен, всё работает через Bash.
