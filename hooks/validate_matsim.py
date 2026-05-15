#!/usr/bin/env python3
"""
PreToolUse hook for MATSim transport modeling project.

Срабатывает перед Edit/Write на файлы MATSim. Проверяет критичные правила
из ~/.claude/skills/transport-modeling/references/rules.md и блокирует редактирование
если видит нарушения.

Покрывает:
- config.xml: flowCapacityFactor == storageCapacityFactor, endTime обязателен
- network.xml: freespeed в м/с (не в км/ч)

Все остальные правки пропускает.
"""
import io
import json
import re
import sys
from pathlib import Path

# На Windows консольная кодировка по умолчанию cp1251 — ломается на кириллице и ≠.
# Форсируем UTF-8 для stdout/stderr.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# Только эти расширения и имена нас интересуют
MATSIM_PATTERNS = ("config.xml", "network.xml", "transitschedule.xml",
                   "transitvehicles.xml", "plans.xml", "population.xml")


def is_matsim_file(file_path: str) -> str | None:
    """Вернуть тип файла MATSim или None если это не MATSim-файл."""
    if not file_path:
        return None
    name = file_path.lower().replace("\\", "/").rsplit("/", 1)[-1]
    if "config" in name and name.endswith(".xml"):
        return "config"
    if "network" in name and name.endswith(".xml"):
        return "network"
    if "transitschedule" in name:
        return "transitschedule"
    if "transitvehicles" in name:
        return "transitvehicles"
    if ("plans" in name or "population" in name) and name.endswith(".xml"):
        return "plans"
    return None


def get_new_content(tool_input: dict) -> str:
    """Извлечь новое содержимое для проверки (для Edit — new_string, для Write — content)."""
    return tool_input.get("new_string") or tool_input.get("content") or ""


def get_full_file_content(file_path: str, tool_input: dict) -> str:
    """
    Получить ИТОГОВОЕ содержимое файла после применения правки.
    Для Write: tool_input['content'].
    Для Edit: читаем файл с диска и применяем замену.
    """
    if "content" in tool_input:
        return tool_input["content"]
    # Edit case: try to reconstruct post-edit content
    try:
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if file_path and Path(file_path).exists():
            current = Path(file_path).read_text(encoding="utf-8", errors="replace")
            if old and old in current:
                return current.replace(old, new, 1)
    except Exception:
        pass
    # Fallback: just the new fragment (less context, fewer checks)
    return get_new_content(tool_input)


# ============================================================
#  Validators — каждый возвращает список ошибок (пустой если OK)
# ============================================================

def validate_config(full_content: str, fragment: str) -> list[str]:
    """Проверки для MATSim config.xml."""
    errors: list[str] = []

    # 1. flowCapacityFactor и storageCapacityFactor должны совпадать
    flow_match = re.search(
        r'name\s*=\s*"flowCapacityFactor"\s+value\s*=\s*"([^"]+)"',
        full_content, re.IGNORECASE
    )
    store_match = re.search(
        r'name\s*=\s*"storageCapacityFactor"\s+value\s*=\s*"([^"]+)"',
        full_content, re.IGNORECASE
    )
    if flow_match and store_match:
        try:
            flow = float(flow_match.group(1))
            store = float(store_match.group(1))
            if abs(flow - store) > 1e-6:
                errors.append(
                    f"flowCapacityFactor={flow} ≠ storageCapacityFactor={store}. "
                    f"По правилу Q1 они ОБЯЗАНЫ совпадать и равняться доле выборки "
                    f"(sample=10% → оба = 0.1). Несовпадение даёт либо gridlock, либо нереальную пропускную способность."
                )
            if flow > 1.0:
                errors.append(
                    f"flowCapacityFactor={flow} > 1.0 — это невозможное значение. "
                    f"Допустимый диапазон (0, 1]. См. правило Q1."
                )
        except ValueError:
            pass

    # 2. endTime должен быть задан в qsim модуле
    qsim_block = re.search(
        r'<module\s+name\s*=\s*"qsim"[^>]*>(.*?)</module>',
        full_content, re.IGNORECASE | re.DOTALL
    )
    if qsim_block:
        body = qsim_block.group(1)
        end_time_match = re.search(
            r'name\s*=\s*"endTime"\s+value\s*=\s*"([^"]*)"',
            body, re.IGNORECASE
        )
        if not end_time_match or not end_time_match.group(1).strip():
            errors.append(
                "В модуле qsim не задан endTime. По правилу Q3 это обязательный параметр — "
                "без него один застрявший агент подвешивает симуляцию навечно. "
                "Поставь например <param name=\"endTime\" value=\"30:00:00\" />."
            )

    return errors


def validate_network(full_content: str, fragment: str) -> list[str]:
    """Проверки для MATSim network.xml. Главное — freespeed в м/с, не в км/ч."""
    errors: list[str] = []
    warnings: list[str] = []

    # Ищем все freespeed в новом фрагменте (не во всём файле — иначе шумно)
    freespeed_values = re.findall(r'freespeed\s*=\s*"([0-9.]+)"', fragment)
    suspicious: list[float] = []
    for v in freespeed_values:
        try:
            val = float(v)
            if val > 50.0:
                # 50 м/с = 180 км/ч — выше уже только Формула-1.
                # Скорее всего пользователь забыл разделить на 3.6.
                suspicious.append(val)
        except ValueError:
            pass

    if suspicious:
        examples = ", ".join(f"{v} → должно быть ~{v/3.6:.2f}" for v in suspicious[:3])
        errors.append(
            f"Найдены подозрительные freespeed > 50 м/с: {suspicious}. "
            f"По правилу N4 freespeed измеряется в МЕТРАХ В СЕКУНДУ, не в км/ч. "
            f"Конвертация: значение_кмч ÷ 3.6 = значение_мс. "
            f"Примеры: {examples}. "
            f"Если ты действительно хочешь скорости >180 км/ч (Формула-1?) — пропусти этот хук вручную."
        )

    return errors


def validate_plans(full_content: str, fragment: str) -> list[str]:
    """Проверки для plans.xml/population.xml — пока минимум."""
    return []


VALIDATORS = {
    "config": validate_config,
    "network": validate_network,
    "plans": validate_plans,
}


# ============================================================
#  Main
# ============================================================

def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Не удалось разобрать payload — пропускаем (не блокируем работу)
        sys.exit(0)

    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    file_type = is_matsim_file(file_path)

    if not file_type:
        # Не MATSim-файл — выходим, ничего не делаем
        sys.exit(0)

    validator = VALIDATORS.get(file_type)
    if validator is None:
        sys.exit(0)

    fragment = get_new_content(tool_input)
    full = get_full_file_content(file_path, tool_input)

    errors = validator(full, fragment)

    if errors:
        reason = (
            f"MATSim {file_type}.xml validation failed:\n\n"
            + "\n\n".join(f"• {e}" for e in errors)
            + "\n\nИсправь и попробуй снова, либо обратись к правилам в "
              "~/.claude/skills/transport-modeling/references/rules.md."
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    # Всё чисто — пропускаем правку
    sys.exit(0)


if __name__ == "__main__":
    main()
