# scheduler.py
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from .admin.notification import (
    send_notification,
    service_expiry_notifier_task,
)
from .database import (
    AsyncSessionLocal,
    CategorySetting,
    Config,
    # FreeTestPlan,
    NotificationRule,
    Plan,
    Service,
    Session,
)


def _fetch_active_services():
    """Synchronous helper: fetch all active services with their plans."""
    with Session() as session:
        return (
            session.query(Service, Plan)
            .join(Plan, Service.plan_id == Plan.id)
            .filter(Service.is_active == 1)
            .all()
        )


def _get_category_setting(category: str):
    """Synchronous helper: get category settings."""
    return CategorySetting.get(category)


def _get_config_stock(plan_id: int):
    """Synchronous helper: get config stock for a plan."""
    return Config.get_stock(plan_id)
from .handlers_admin import process_waiting_queue
from .helpers import (
    alert_admins,
    get_all_pending_plans,
)
from .utils import get_panel
TIMEOUT = 1


def _fmt_mb(value_bytes: int) -> str:
    return f"{value_bytes / (1024 * 1024):.1f}"


def _parse_expire_dt(expire_value):
    if not expire_value:
        return None

    if isinstance(expire_value, datetime):
        return expire_value if expire_value.tzinfo else expire_value.replace(tzinfo=timezone.utc)

    try:
        # timestamp (sec)
        if isinstance(expire_value, (int, float)):
            return datetime.fromtimestamp(expire_value, tz=timezone.utc)

        s = str(expire_value).strip()
        # timestamp string
        if s.isdigit():
            return datetime.fromtimestamp(int(s), tz=timezone.utc)

        # iso string
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _get_usage_values(panel_user: dict):
    used = panel_user.get("used_traffic")
    if used is None:
        up = panel_user.get("upload") or 0
        down = panel_user.get("download") or 0
        used = up + down
    total = panel_user.get("data_limit")
    if total is None:
        total = panel_user.get("total_traffic")

    try:
        used_i = int(used or 0)
    except Exception:
        used_i = 0
    try:
        total_i = int(total or 0)
    except Exception:
        total_i = 0

    return used_i, total_i


async def service_usage_reminder_task(bot: Bot):
    """Send usage/time notifications for active normal services.

    Sends notifications when:
    - 90% of service volume has been consumed
    - Service time has expired
    """
    while True:
        try:
            enabled_rules = {
                "service_volume_90": await asyncio.to_thread(NotificationRule.get_enabled, "service_volume_90"),
                "service_time_expired": await asyncio.to_thread(NotificationRule.get_enabled, "service_time_expired"),
            }

            if not any(r and r.message for r in enabled_rules.values()):
                await asyncio.sleep(TIMEOUT)
                continue


            now = datetime.now(timezone.utc)
            # free_test_plan_id = FreeTestPlan.get_plan_id()

            services = await asyncio.to_thread(_fetch_active_services)

            for svc, plan in services:
                    # Skip free test plans
                    # if free_test_plan_id and plan.id == free_test_plan_id:
                    #     continue
                    # Skip free plans (price <= 0)
                    if plan.price <= 0:
                        continue

                    try:
                        panel = await get_panel(plan.category)
                        if not await panel.is_alive():
                            await asyncio.sleep(TIMEOUT)
                            continue
                        active_users = await panel.get_active_users()
                    except Exception as e:
                        logging.error(f"Service usage reminder: panel unavailable: {e}")
                        await asyncio.sleep(TIMEOUT)
                        continue

                    by_username = {}
                    for u in active_users:
                        username = u.get("username") or u.get("email")
                        if username:
                            by_username[username] = u

                    service_name = svc.service_name
                    if not service_name:
                        continue

                    panel_user = by_username.get(service_name)
                    if not panel_user:
                        continue

                    used_bytes, total_bytes = _get_usage_values(panel_user)
                    remaining_bytes = max(0, total_bytes - used_bytes) if total_bytes > 0 else 0

                    expire_dt = _parse_expire_dt(panel_user.get("expire") or svc.expires_at)
                    seconds_left = int((expire_dt - now).total_seconds()) if expire_dt else None

                    expire_text = expire_dt.strftime("%Y-%m-%d %H:%M") if expire_dt else "-"

                    # Calculate remaining time
                    remaining_time = "-"
                    if seconds_left is not None:
                        if seconds_left <= 0:
                            remaining_time = "0m"
                        else:
                            hours = seconds_left // 3600
                            minutes = (seconds_left % 3600) // 60
                            remaining_time = f"{hours}h {minutes}m"

                    template_vars = {
                        "service_name": plan.name,
                        "used_mb": _fmt_mb(used_bytes),
                        "remaining_mb": _fmt_mb(remaining_bytes),
                        "total_mb": _fmt_mb(total_bytes),
                        "remaining_time": remaining_time,
                        "expire_at": expire_text,
                        "service_id": svc.id,
                        "category": plan.category or "",
                    }

                    # 90% volume consumed check (only for plans with volume limit)
                    if total_bytes > 0:
                        usage_percent = (used_bytes / total_bytes) * 100
                        print(f"{usage_percent} {service_name}")
                        if (
                            enabled_rules["service_volume_90"]
                            and enabled_rules["service_volume_90"].message
                            and usage_percent >= 90
                        ):
                            await send_notification(
                                user_id=svc.user_id,
                                type_key="service_volume_90",
                                target_id=svc.id,
                                **template_vars,
                            )

                    # Time expired check
                    if (
                        enabled_rules["service_time_expired"]
                        and enabled_rules["service_time_expired"].message
                        and seconds_left is not None
                        and seconds_left <= 0
                    ):
                        await send_notification(
                            user_id=svc.user_id,
                            type_key="service_time_expired",
                            target_id=svc.id,
                            **template_vars,
                        )

        except Exception as e:
            logging.exception(f"Service usage reminder task error: {e}")

        await asyncio.sleep(TIMEOUT)

async def queue_config_creator_task(bot: Bot):
    """
    Fully independent background task (separate from auto_stock_refiller_task).
    Every 30 seconds: for each plan that has queued orders, creates exactly as
    many new panel configs as are still missing, then fulfills the queue.

    NOTE: DB sessions are kept short-lived; no transaction is held open
    across panel API calls (prevents SQLite 'database is locked').
    """

    while True:
        try:
            pending_plans = await asyncio.to_thread(get_all_pending_plans)  # [{plan_id, name, waiting_count}, ...]
            if not pending_plans:
                await asyncio.sleep(TIMEOUT)
                continue

            for p in pending_plans:
                # 1. Fetch plan fields in a SHORT session, detach into a plain dict
                async with AsyncSessionLocal() as session:
                    plan_obj = await session.get(Plan, p["plan_id"])
                    if not plan_obj:
                        continue
                    plan = {
                        "id": plan_obj.id,
                        "name": plan_obj.name,
                        "category": plan_obj.category,
                        "volume_gb": plan_obj.volume_gb,
                        "duration_days": plan_obj.duration_days,
                        "max_devices": plan_obj.max_devices,
                    }

                category_setting = await asyncio.to_thread(_get_category_setting, plan["category"])
                if not category_setting or category_setting.get("connect_to_panel") == 0:
                    continue

                panel_label = "Pasarguard"
                try:
                    panel = await get_panel(plan["category"])
                    if not await panel.is_alive():
                        continue

                except Exception as e:
                    logging.debug(f"Auto Stock Refiller: Main panel check failed: {e}")
                    continue

                try:
                    # 2. Stock count via its own short-lived session

                    existing_stock = await asyncio.to_thread(_get_config_stock, plan["id"])

                    needed_count = p["waiting_count"] - existing_stock
                    if needed_count <= 0:
                        await process_waiting_queue(plan["id"])  # stock already covers the queue
                        continue

                    logging.info(
                        f"Queue Config Creator [{panel_label}]: Plan '{plan['name']}' needs "
                        f"{needed_count} account(s) for {p['waiting_count']} queued order(s)."
                    )

                    created_clients = []
                    for _ in range(needed_count):
                        total_gb = plan["volume_gb"] if plan["volume_gb"] and plan["volume_gb"] > 0 else None
                        expiry_days = (
                            plan["duration_days"] if plan["duration_days"] and plan["duration_days"] > 0 else None
                        )
                        max_connections = (
                            plan["max_devices"] if plan["max_devices"] and plan["max_devices"] >= 0 else None
                        )
                        note = f"# QUEUE-FILL - {plan['name']}"

                        max_retries = 4
                        for attempt in range(max_retries):
                            try:
                                user = await panel.create_client(
                                    total_gb=total_gb,
                                    expiry_time=expiry_days,
                                    limit_ip=max_connections,
                                    note=note,
                                )
                                created_clients.append(user)
                                await asyncio.sleep(0.5)
                                break
                            except Exception as e:
                                if attempt < max_retries - 1:
                                    logging.warning(f"Panel error, retry {attempt + 1}/{max_retries}: {e}")
                                    await asyncio.sleep(2)
                                else:
                                    logging.error(f"Failed to create after {max_retries} retries: {e}")

                    if created_clients:
                        db_created_count = 0
                        # Save in a NEW short session (no txn open during panel work)
                        async with AsyncSessionLocal() as session:
                            for user in created_clients:
                                try:
                                    new_config = Config(
                                        plan_id=plan["id"],
                                        config_data=user.subscription_url,
                                        # type="panel",
                                        is_used=0,
                                        service_name=user.username,
                                    )
                                    session.add(new_config)
                                    db_created_count += 1
                                except Exception as db_err:
                                    logging.error(f"Failed to save config for '{user.username}': {db_err}")

                            if db_created_count > 0:
                                await session.commit()

                        if db_created_count > 0:
                            await alert_admins(
                                bot,
                                text=(
                                    f"🧾 پر کردن صف انتظار ({panel_label})\n\n"
                                    f"📦 پلن: {plan['name']}\n"
                                    f"⏳ در صف: {p['waiting_count']}\n"
                                    f"✅ تعداد ایجاد شده: {db_created_count}"
                                ),
                            )

                    # Now that stock exists (old + newly created), fulfill the queue.
                    await process_waiting_queue(plan["id"])

                except Exception as e:
                    logging.exception(f"Queue Config Creator: Error processing plan '{plan['name']}': {e}")

        except Exception as e:
            logging.exception(f"Queue Config Creator: General error - {e}")

        await asyncio.sleep(30)


async def start_scheduler(bot: Bot):
    """Start all background scheduler tasks"""
    asyncio.create_task(service_usage_reminder_task(bot))
    asyncio.create_task(queue_config_creator_task(bot))
    asyncio.create_task(service_expiry_notifier_task(bot))
