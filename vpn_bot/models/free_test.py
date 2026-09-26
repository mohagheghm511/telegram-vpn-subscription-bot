from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy import text as stext
from sqlalchemy.ext.asyncio import AsyncSession

from .base import Base, provide_session


class FreeTest(Base):
    __tablename__ = "free_tests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, unique=True, nullable=False)
    used_at = Column(String, server_default=func.datetime("now"))


class FreeTestUsage(Base):
    """Track when users receive free tests for the 7-day cooldown"""

    __tablename__ = "free_test_usage"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    service_id = Column(Integer, nullable=False)
    received_at = Column(String, server_default=func.datetime("now"))
    feedback_sent = Column(Integer, server_default=stext("0"))

    __table_args__ = (UniqueConstraint("user_id", "service_id", name="uq_user_service"),)

    @classmethod
    @provide_session
    async def can_get_free_test(cls, user_id: int, session: AsyncSession = None) -> tuple[bool, int]:
        from vpn_bot.database import Setting

        try:
            days = int(Setting.get("free_test_days", "7"))
        except (TypeError, ValueError):
            days = 7
        stmt = (
            select(cls)
            .where(cls.user_id == user_id)
            .order_by(cls.received_at.desc())
        )
        res = await session.execute(stmt)
        last_usage = res.scalars().first()

        if not last_usage:
            return True, 0

        try:
            last_date = datetime.fromisoformat(last_usage.received_at)
            now = datetime.now()
            days_since = (now - last_date).days

            if days_since >= days:
                return True, 0
            else:
                return False, days - days_since
        except Exception:
            return True, 0

    @classmethod
    @provide_session
    async def get_active_free_test_service(
        cls, user_id: int, session: AsyncSession = None
    ) -> dict[str, Any] | None:
        from vpn_bot.database import Plan, Config, Service

        stmt = (
            select(
                Service,
                Plan.name.label("plan_name"),
                Plan.category.label("category"),
                Config.config_data,
                Config.password,
            )
            .select_from(cls)
            .join(Service, cls.service_id == Service.id)
            .join(Plan, Service.plan_id == Plan.id)
            .join(Config, Service.config_id == Config.id)
            .where(cls.user_id == user_id, Service.is_active == 1)
            .order_by(cls.received_at.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        row = res.first()
        if not row:
            return None

        service_obj = row[0]
        data = {c.name: getattr(service_obj, c.name) for c in service_obj.__table__.columns}
        data.update({
            "plan_name": row.plan_name,
            "category": row.category,
            "config_data": row.config_data,
            "password": row.password,
        })
        return data

    @classmethod
    @provide_session
    async def record_usage(cls, user_id: int, service_id: int, session: AsyncSession = None) -> "FreeTestUsage":
        usage = cls(user_id=user_id, service_id=service_id)
        session.add(usage)
        await session.flush()
        return usage

    # @classmethod
    # @provide_session
    # async def get_pending_feedback_users(cls, session: AsyncSession = None) -> List[Dict[str, Any]]:
    #     from .settings import Setting
    #     from .user import User

    #     t = int(float(await Setting.get("free_test_time_check", "1")) * 60)
    #     five_hours_ago = (datetime.now() - timedelta(minutes=t)).isoformat()

    #     stmt = (
    #         select(
    #             cls,
    #             User.telegram_id,
    #             User.full_name,
    #             User.username,
    #         )
    #         .join(User, cls.user_id == User.telegram_id)
    #         .where(cls.feedback_sent == 0, cls.received_at <= five_hours_ago)
    #     )
    #     res = await session.execute(stmt)

    #     results = []
    #     for row in res.all():
    #         usage_obj = row[0]
    #         data = {c.name: getattr(usage_obj, c.name) for c in usage_obj.__table__.columns}
    #         data.update({
    #             "telegram_id": row.telegram_id,
    #             "full_name": row.full_name,
    #             "username": row.username,
    #         })
    #         results.append(data)

    #     return results

    @classmethod
    @provide_session
    async def mark_feedback_sent(cls, usage_id: int, session: AsyncSession = None):
        stmt = (
            update(cls)
            .where(cls.id == usage_id)
            .values(feedback_sent=1)
        )
        await session.execute(stmt)

    @classmethod
    @provide_session
    async def get_active_services_for_reminder(cls, session: AsyncSession = None) -> list[dict[str, Any]]:
        from vpn_bot.database import Plan, Config, Service


        stmt = (
            select(
                cls.id.label("usage_id"),
                cls.user_id,
                cls.service_id,
                Service.service_name,
                Service.expires_at,
                Service.volume_gb,
                Plan.category,
                Plan.name.label("plan_name"),
                Config.config_data,
            )
            .join(Service, Service.id == cls.service_id)
            .join(Plan, Plan.id == Service.plan_id)
            .join(Config, Config.id == Service.config_id)
            .where(Service.is_active == 1)
        )
        res = await session.execute(stmt)
        return [dict(r._mapping) for r in res.all()]


class FreeTestPlan(Base):
    """Store the free test plan configuration - only one allowed"""

    __tablename__ = "free_test_plan"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, unique=True, nullable=False)
    is_active = Column(Integer, server_default=stext("1"))
    created_at = Column(String, server_default=func.datetime("now"))

    @classmethod
    @provide_session
    async def get_active(cls, session: AsyncSession = None) -> dict | None:
        from vpn_bot.database import Plan

        stmt = (
            select(cls, Plan)
            .join(Plan, cls.plan_id == Plan.id)
            .where(cls.is_active == 1)
            .limit(1)
        )
        result = (await session.execute(stmt)).first()
        if not result:
            return None

        free_test, plan = result
        plan_dict = {col.name: getattr(plan, col.name) for col in plan.__table__.columns}
        free_test_dict = {col.name: getattr(free_test, col.name) for col in free_test.__table__.columns}

        return {**plan_dict, **free_test_dict}

    @classmethod
    @provide_session
    async def set_plan(cls, plan_id: int, session: AsyncSession = None) -> tuple[bool, str]:
        from ..formatting import infinit_or_real
        from vpn_bot.database import Plan


        plan = (await session.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()
        if not plan:
            return False, "پلن یافت نشد"

        volume_display = infinit_or_real(plan.volume_gb, "گیگ")
        duration_display = infinit_or_real(plan.duration_days, "روز")
        max_devices = infinit_or_real(plan.max_devices, "")
        info = (
            f"📦 پلن: {plan.name}\n"
            f"📊 حجم: {volume_display}\n"
            f"🕓 مدت: {duration_display}\n"
            f"👥 دستگاه: {max_devices}\n"
            f"💰 قیمت فعلی: {plan.price:,} تومان\n\n"
            f"⚠️ با تایید شما:\n"
            f"• قیمت → 0 تومان\n"
            f"• قیمت پایه حجم → خالی (غیرقابل تمدید حجم)\n"
            f"• قیمت پایه روز → خالی (غیرقابل تمدید زمان)\n"
            f"• از لیست خرید کاربران مخفی می‌شود"
        )
        return True, info

    @classmethod
    @provide_session
    async def confirm_set_plan(cls, plan_id: int, session: AsyncSession = None) -> bool:
        import logging

        from vpn_bot.database import Plan

        try:
            await session.execute(update(cls).values(is_active=0))

            stmt = select(cls).where(cls.plan_id == plan_id)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.is_active = 1
            else:
                session.add(cls(plan_id=plan_id, is_active=1))

            await session.execute(
                update(Plan)
                .where(Plan.id == plan_id)
                .values(price=0)
            )
            return True
        except Exception as e:
            logging.error(f"Error confirming free test plan: {e}")
            return False

    @classmethod
    @provide_session
    async def remove_plan(cls, session: AsyncSession = None) -> tuple[bool, int | None]:
        import logging
        try:
            stmt = select(cls).where(cls.is_active == 1)
            current = (await session.execute(stmt)).scalar_one_or_none()
            previous_plan_id = current.plan_id if current else None

            await session.execute(update(cls).values(is_active=0))
            return True, previous_plan_id
        except Exception as e:
            logging.error(f"Error removing free test plan: {e}")
            return False, None

    @classmethod
    @provide_session
    async def get_plan_id(cls, session: AsyncSession = None) -> int | None:
        stmt = select(cls.plan_id).where(cls.is_active == 1)
        return (await session.execute(stmt)).scalar_one_or_none()


class FreeTestConfig(Base):
    __tablename__ = "free_test_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_data = Column(String, nullable=False)
    description = Column(String)
    is_used = Column(Integer, server_default=stext("0"))
    assigned_to = Column(Integer)
    assigned_at = Column(String)
    created_at = Column(String, server_default=func.datetime("now"))

    @classmethod
    @provide_session
    async def has_used(cls, user_id: int, session: AsyncSession = None) -> bool:
        stmt = select(cls.id).where(cls.assigned_to == user_id)
        res = await session.execute(stmt)
        return res.first() is not None

    @classmethod
    @provide_session
    async def get(cls, session: AsyncSession = None) -> Optional["FreeTestConfig"]:
        stmt = select(cls).where(cls.is_used == 0).order_by(cls.id)
        res = await session.execute(stmt)
        return res.scalars().first()

    @classmethod
    @provide_session
    async def assign_to(
        cls, user_id: int, config_id: int, session: AsyncSession = None
    ) -> bool:
        stmt = select(cls).where(cls.id == config_id).with_for_update()
        res = await session.execute(stmt)
        config = res.scalars().first()

        if config:
            config.is_used = 1
            config.assigned_to = user_id
            config.assigned_at = datetime.now().isoformat()
            return True
        return False

    @classmethod
    @provide_session
    async def stock(cls, session: AsyncSession = None) -> int:
        stmt = select(func.count(cls.id)).where(cls.is_used == 0)
        res = await session.execute(stmt)
        return res.scalar_one_or_none() or 0

    @classmethod
    @provide_session
    async def add(
        cls, config_data: str, description: str = "", session: AsyncSession = None
    ) -> int:
        config = cls(config_data=config_data, description=description)
        session.add(config)
        await session.flush()
        return config.id

    @classmethod
    @provide_session
    async def delete(cls, config_id: int, session: AsyncSession = None) -> bool:
        config = await session.get(cls, config_id)
        if config:
            await session.delete(config)
            return True
        return False
