# MCP Servers

MCP-серверы для работы с MATSim.

## Реализовано

- **`matsim-tools/`** — 4 инструмента поверх `../tools/`: `get_network_summary`,
  `get_simulation_metrics`, `modify_network`, `run_simulation`. См. `matsim-tools/README.md`.

## Возможные расширения

- `validate_config(path)` — структурированная валидация config.xml
- `compute_modal_split(events_xml)` — расчёт modal split из events
- `suggest_asc_adjustment(observed, target, current_asc)` — формула C4
- `lookup_rk_speed_limit(road_type, inside_city)` — таблица К1–К4
- `convert_osm_to_network(osm_path, output_path)` — OSM → MATSim network
- `diagnose_stuck_simulation(log_path)` — анализ зависшего прогона
- `pt-tools/` — инструменты для общественного транспорта (расписания, маршруты)
