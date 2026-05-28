# Claude MATSim Toolkit

Набор инструментов для работы с транспортными моделями (MATSim) через Claude Code и другие AI-агенты.

Цель — дать AI-ассистенту проверенные доменные знания и автоматические защитные механизмы при работе с транспортными моделями, чтобы он не выдумывал значения и не делал типовые ошибки конфигурации.

> **Статус разработки:** см. [PROGRESS.md](PROGRESS.md) — живой отчёт о реализованных фичах, проверках и планах.

## Состав

```
claude-matsim-toolkit/
├── skills/
│   └── transport-modeling/        Скилл — база ~60 правил из 4 источников
├── hooks/
│   ├── validate_matsim.py         PreToolUse-хук валидации MATSim XML
│   └── test-fixtures/             Тестовые XML для проверки хука
├── mcp-servers/                   (Зарезервировано под будущие MCP-серверы)
├── tests/
│   └── test_hooks.py              Автотесты хука
├── examples/
│   └── settings.example.json      Пример регистрации хука в Claude Code
└── install/
    ├── install.ps1                Установка на Windows (PowerShell)
    └── install.sh                 Установка на macOS / Linux
```

## Источники знаний

| Тег | Источник |
|-----|----------|
| `[M]` | MATSim Book, 2016 ed. — https://www.matsim.org/the-book |
| `[G]` | А. Э. Горев, «Основы теории транспортных систем», СПбГАСУ, 2010 |
| `[RK]` | ПДД РК, Приказ МВД РК №534 от 30.06.2023 |
| `[SP]` | СП РК 3.03-101-2013 «Автомобильные дороги» |

Все правила в `skills/transport-modeling/references/rules.md` снабжены ссылками на страницу/статью первоисточника.

## Установка

### Windows

```powershell
git clone https://github.com/<your-user>/claude-matsim-toolkit.git
cd claude-matsim-toolkit
./install/install.ps1
```

### macOS / Linux

```bash
git clone https://github.com/<your-user>/claude-matsim-toolkit.git
cd claude-matsim-toolkit
./install/install.sh
```

Скрипт делает три вещи:

1. Копирует `skills/transport-modeling/` в `~/.claude/skills/transport-modeling/`
2. Копирует `hooks/validate_matsim.py` в `~/.claude/hooks/`
3. Печатает блок JSON для добавления в `~/.claude/settings.json` (вручную, чтобы не затирать твои существующие настройки)

## Использование

### Скилл

Триггерится автоматически когда ты работаешь с MATSim-файлами или задаёшь вопросы по транспортному моделированию. Подробнее — в `skills/transport-modeling/SKILL.md`.

### Хук

Срабатывает перед каждым Edit/Write. Блокирует запись с пояснением если видит:

- `flowCapacityFactor ≠ storageCapacityFactor` в `config.xml`
- Отсутствие `endTime` в модуле `qsim`
- `freespeed > 50` в `network.xml` (почти всегда означает что значение в км/ч вместо м/с)

Все остальные файлы пропускаются молча.

## Тестирование

```bash
python tests/test_hooks.py
```

Запускает все сценарии (плохой config, хороший config, плохой network, не-MATSim файл) и проверяет что хук блокирует/пропускает как ожидается.

## Расширение

### Добавить правило в скилл

1. Открой `skills/transport-modeling/references/rules.md`
2. Найди подходящую категорию (A/Q/S/C/R/N/P/T/K/D) или заведи новую
3. Добавь строку с правилом + ссылкой на источник
4. Если правило критичное (нужно знать в любом MATSim-вопросе) — продублируй в `SKILL.md`

### Добавить проверку в хук

Открой `hooks/validate_matsim.py`, добавь функцию `validate_<тип_файла>` и зарегистрируй её в словаре `VALIDATORS`. Каждый валидатор принимает полный текст файла и фрагмент правки, возвращает список ошибок (строк).

### Будущие направления

- MCP-сервер с инструментами `validate_config`, `compute_modal_split`, `convert_osm_to_network`, `lookup_rk_speed_limit`
- Хуки для `plans.xml` (проверка S7 — первая/последняя активность одного типа)
- Хук для `transitSchedule.xml` (проверка наличия `awaitDeparture` и линковки stops к link)
- UserPromptSubmit-хук для автоматической инжекции контекста по ключевым словам

## Лицензия

MIT — см. `LICENSE`.
