# MCP Servers (зарезервировано)

Эта папка зарезервирована под будущие MCP-серверы для работы с MATSim.

## Что может появиться здесь

- `matsim-tools/` — сервер с инструментами:
  - `validate_config(path)` — структурированная валидация config.xml
  - `compute_modal_split(events_xml)` — расчёт modal split из events
  - `suggest_asc_adjustment(observed, target, current_asc)` — формула C4
  - `lookup_rk_speed_limit(road_type, inside_city)` — таблица К1–К4
  - `convert_osm_to_network(osm_path, output_path)` — OSM → MATSim network
  - `diagnose_stuck_simulation(log_path)` — анализ зависшего прогона

- `pt-tools/` — инструменты для общественного транспорта (анализ расписаний, оптимизация маршрутов).

Решение когда добавлять MCP — после того как накопится база реальных повторяющихся задач, которые удобнее автоматизировать чем описывать в скилле.
