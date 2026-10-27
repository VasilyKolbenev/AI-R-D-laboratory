"""Read-only rolling reservation availability; never changes limits or approvals."""
from datetime import datetime, timedelta, timezone
import json


def snapshot(db, limit, required, at):
    from .orchestration import call_reservation
    cutoff = (at - timedelta(hours=24)).isoformat(timespec="seconds")
    reservations = [(datetime.fromisoformat(row["approved_at"]),
                     call_reservation(json.loads(row["plan"]))) for row in
                    db.execute("SELECT approved_at,plan FROM runs WHERE approved_at>=? ORDER BY approved_at", (cutoff,))]
    used = sum(calls for _, calls in reservations)
    available = max(0, limit - used)
    eligible = None
    if required <= limit and required > available:
        remaining = used
        for approved, calls in reservations:
            remaining -= calls
            if remaining + required <= limit:
                # The guard includes the cutoff second (approved_at >= cutoff).
                # Display the first whole second when the old approval is out.
                eligible = (approved.replace(microsecond=0) + timedelta(hours=24, seconds=1)).isoformat()
                break
    return {"limit": limit, "used": used, "required": required, "available": available,
            "can_start": required <= available, "next_eligible_at": eligible,
            "checked_at": at.isoformat(timespec="seconds")}


def notice(budget):
    text = (f"Локальный бюджет за скользящие 24 часа: занято {budget['used']} из {budget['limit']} вызовов CLI. "
            f"Для этого плана нужно {budget['required']}, доступно {budget['available']}.")
    if budget['can_start']:
        return text + " Доступность повторно проверяется при апруве. Это локальный предел, не остаток лимита провайдера."
    if budget['required'] > budget['limit']:
        text += " План требует больше установленного предела; ожидание не освободит достаточно бюджета. Изменить предел можно в Настройках."
    elif budget['next_eligible_at']:
        available_at = datetime.fromisoformat(budget['next_eligible_at']).astimezone(timezone(timedelta(hours=3)))
        text += (" По текущему журналу повторить апрув можно с " + available_at.strftime('%d.%m.%Y %H:%M:%S') +
                 " МСК, если до этого не будет других запусков и изменений лимита.")
    text += " Обновление плана и смена исполнителя бюджет не освобождают. "
    if budget['next_eligible_at']:
        text += "После освобождения нажми кнопку апрува у действующего плана. "
    return text + "Автоматического запуска нет. Лимит не изменён."
