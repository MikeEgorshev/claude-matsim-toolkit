# tools/ — слой действий

Python CLI-инструменты, которыми LLM-агент управляет моделью MATSim. Каждый
инструмент: вход = пути/параметры, выход = компактный JSON. Только стандартная
библиотека Python (никаких pip install). Поддерживают `.gz` прозрачно.

Агент вызывает их через Bash и получает JSON — он никогда не читает сырой XML/CSV сам.

## Read-only (безопасные, ничего не меняют)

### `matsim_summary.py` — сводка входных файлов
```bash
python matsim_summary.py --network network.xml.gz --plans plans.xml.gz --pretty
```
Возвращает: число узлов/звеньев, диапазоны freespeed (м/с) и capacity (авт/ч),
типы дорог, размер популяции, типы активностей, режимы поездок. Предупреждает
если freespeed > 50 м/с (вероятно значение случайно оставлено в км/ч — правило N4).

### `matsim_metrics.py` — метрики результата симуляции
```bash
python matsim_metrics.py output/ --pretty
```
Парсит штатные `scorestats.csv` / `modestats.csv` / `traveldistancestats.csv`.
Возвращает: число итераций, эволюцию score (начало/конец/дельта), modal split
(начальный и финальный), среднюю дальность поездки. Это контур обратной связи —
агент по нему оценивает стала ли модель лучше.

### `matsim_run.py` — запуск симуляции
```bash
python matsim_run.py --jar app.jar --main-class org.matsim.project.RunShamalgan \
    --config scenarios/shamalgan/config.xml --iterations 100 \
    --output runs/exp_100it --threads 7 --cwd <корень проекта> --summarize
```
Огромный stdout MATSim уходит в лог-файл, агенту возвращается компактный JSON
(статус, exit code, длительность, путь к логу, опц. метрики через `--summarize`).
Длинные прогоны — в фон (в Claude Code: Bash с `run_in_background`). Есть `--dry-run`
чтобы проверить собранную команду без запуска. Переопределения итераций/папки идут
через штатные MATSim-оверрайды `--config:controler.lastIteration=N` и
`--config:controler.outputDirectory=DIR` — ничего в самом config.xml не меняется.

## Изменяющие (с валидацией и защитой оригинала)

### `matsim_modify.py` — типизированное изменение network.xml
```bash
# Закрыть мост для авто (записать в копию)
python matsim_modify.py --network net.xml --output net_closed.xml --links 456 --close-link

# Поднять capacity и задать скорость из км/ч; посмотреть что изменится без записи
python matsim_modify.py --network net.xml --output net2.xml \
    --links 12,13,14 --set-capacity 1200 --set-freespeed-kmh 60 --dry-run --pretty
```
Операции (комбинируются): `--set-capacity`, `--set-freespeed` (м/с),
`--set-freespeed-kmh` (÷3.6 автоматически), `--set-lanes` (→ permlanes),
`--remove-modes`, `--close-link` (= убрать car). Валидация ДО записи: capacity/freespeed > 0,
link существует, freespeed-варнинг при > 50 м/с. Пишет в КОПИЮ (оригинал защищён,
перезапись только с `--force`). DOCTYPE сети сохраняется. Возвращает JSON со списком
изменений (старое → новое) и предупреждениями.

## Принцип безопасности

Read-only инструменты физически не могут изменить модель. Изменяющие инструменты
(`modify`) валидируют все параметры (диапазоны, типы) до записи в файл — LLM не
может протолкнуть отрицательную capacity или freespeed в км/ч.
