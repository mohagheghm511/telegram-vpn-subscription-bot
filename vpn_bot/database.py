import sqlite3
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Boolean, UniqueConstraint, select
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy import or_, func,Index
from sqlalchemy import text as stext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import json
import logging
from .models.free_test import FreeTest, FreeTestConfig, FreeTestPlan, FreeTestUsage

# DB_PATH = "bot.db"
DB_PATH = "./bot.db"

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

a_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},
)
AsyncSessionLocal = async_sessionmaker(bind=a_engine, expire_on_commit=False, class_=AsyncSession)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



Base = declarative_base()
engine = create_engine(f'sqlite:///{DB_PATH}', echo=False, connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine, expire_on_commit=False)


from sqlalchemy import DateTime
from datetime import datetime

class Tornoment(Base):
    __tablename__ = 'tornoment'
    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String, default='')
    description = Column(String, default='')
    status = Column(String, default='1')
    # guid post link
    link = Column(String, default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=True)

    @classmethod
    def get_all(cls):
        session = Session()
        try:
            return session.query(cls).all()
        finally:
            session.close()

    @classmethod
    def get_by_id(cls, t_id):
        session = Session()
        try:
            return session.query(cls).filter(cls.id == t_id).first()
        finally:
            session.close()

    @classmethod
    def create(cls, name, description, ends_at: datetime, link):
        session = Session()
        try:
            new_tournament = cls(name=name, description=description, ends_at=ends_at, link=link)
            session.add(new_tournament)
            session.commit()
            return new_tournament
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    @classmethod
    def update_field(cls, t_id, field_name, value):
        session = Session()
        try:
            session.query(cls).filter(cls.id == t_id).update({field_name: value})
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    @classmethod
    def delete_by_id(cls, t_id):
        session = Session()
        try:
            session.query(cls).filter(cls.id == t_id).delete()
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    @classmethod
    def get_active_and_running(cls):
        session = Session()
        try:
            return session.query(cls).filter(
                cls.status == '1',
                cls.ends_at > datetime.now()
            ).first()
        finally:
            session.close()

class Invoice(Base):
    __tablename__ = 'invoice'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String, default='pending')
    method = Column(String, default='card') # card and ton
    channel_message_id = Column(Integer)
    text = Column(String, default='')
    chat_message_id = Column(Integer, default=-1)
    created_at = Column(String, default=func.datetime('now'))

    __table_args__ = (
        Index('idx_invoice_status', 'status'),
        Index('idx_invoice_user_status', 'user_id', 'status'),
    )

    @classmethod
    def is_locked(cls, amount, status='pending'):
        session = Session()
        try:
            return (
                session.query(Invoice)
                .filter(
                    Invoice.amount == amount,
                    Invoice.method == 'card',
                    or_(
                        Invoice.status == status,
                        # Invoice.created_at > func.datetime('now', '-1 minute') # DEBUG
                        Invoice.created_at > func.datetime('now', '-24 hours')
                    )
                )
                .first()
            )
        finally:
            session.close()

    @classmethod
    def exists(cls, **kwargs):
        session = Session()
        try:
            return session.query(cls).filter_by(**kwargs).first()
        finally:
            session.close()

    @classmethod
    def confirm(cls, invoice_id, session = None):
        """
        Confirm invoice. If session is provided, use it (for transaction chaining).
        """
        should_close = False
        if session is None:
            session = Session()
            should_close = True

        try:
            obj = (
                session.query(cls)
                .filter(cls.id == invoice_id)
                .with_for_update()
                .first()
            )

            if not obj:
                return None

            if obj.status == 'success':
                return False

            if obj.status != 'pending':
                return None

            obj.status = 'success'

            if should_close:
                session.commit()
                session.refresh(obj)

            return obj
        except Exception as e:
            if should_close:
                session.rollback()
            raise e
        finally:
            if should_close:
                session.close()

    @classmethod
    def reject(cls, invoice_id):
        session = Session()
        try:
            obj = (
                session.query(cls)
                .filter(cls.id == invoice_id)
                .with_for_update()  # Add lock here too
                .first()
            )

            if not obj:
                return None

            # Don't reject already processed invoices
            if obj.status in ('success', 'failed'):
                return False

            obj.status = 'failed'
            session.commit()
            session.refresh(obj)
            return obj
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

class Setting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    varables = Column(Text, server_default=stext("''")) # new
    info = Column(Text, server_default=stext("''")) # new

    @classmethod
    def get_all_msg_settings(cls):
        """Get all settings where key starts with 'msg_' as a list of (key, info)."""
        session = Session()
        settings = session.query(cls).filter(cls.key.like('msg_%')).all()
        session.close()
        return [(str(s.key), str(s.info)) for s in settings]


    @classmethod
    def hint(cls, key, default=''):
        session = Session()
        setting = session.query(cls).filter_by(key=key).first()
        session.close()
        if setting:
            return str(setting.varables)
        return default


    @classmethod
    def get(cls, key, default=''):
        session = Session()
        setting = session.query(cls).filter_by(key=key).first()
        session.close()
        if setting:
            return str(setting.value)
        return default

    @classmethod
    def set(cls, key, value):
        session = Session()
        setting = session.query(cls).filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = cls(key=key, value=str(value))
            session.add(setting)
        session.commit()
        session.close()


class MandatoryChannel(Base):
    __tablename__ = 'mandatory_channels'

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    title = Column(String, nullable=False)
    added_at = Column(String, server_default=func.datetime('now'))

    def to_dict(self):
        return {
            'id': self.id,
            'channel_id': self.channel_id,
            'username': self.username,
            'title': self.title,
            'added_at': self.added_at,
        }

    @classmethod
    def get_all(cls):
        session = Session()
        try:
            rows = session.query(cls).order_by(cls.id).all()
            return [r.to_dict() for r in rows]
        finally:
            session.close()

    @classmethod
    def get_by_id(cls, row_id):
        session = Session()
        try:
            row = session.query(cls).filter(cls.id == row_id).first()
            return row.to_dict() if row else None
        finally:
            session.close()

    @classmethod
    def get_by_channel_id(cls, channel_id):
        session = Session()
        try:
            row = session.query(cls).filter(cls.channel_id == channel_id).first()
            return row.to_dict() if row else None
        finally:
            session.close()

    @classmethod
    def add(cls, channel_id, username, title):
        session = Session()
        try:
            obj = cls(
                channel_id=channel_id,
                username=username or None,
                title=title,
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return True, None
        except IntegrityError:
            session.rollback()
            return False, "duplicate"
        finally:
            session.close()

    @classmethod
    def remove(cls, row_id):
        session = Session()
        try:
            obj = session.query(cls).filter(cls.id == row_id).first()
            if not obj:
                return False
            session.delete(obj)
            session.commit()
            return True
        finally:
            session.close()

from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import aliased


class PendingConfig(Base):
    __tablename__ = "pending_configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    plan_id = Column(Integer, nullable=False)
    amount = Column(Integer, server_default=stext("0"))
    fulfilled_at = Column(String)
    created_at = Column(String, server_default=func.datetime("now"))



class NotificationRule(Base):
    """Per-notification-type configuration: timing, message template, enabled buttons"""

    __tablename__ = "notification_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type_key = Column(String, unique=True, nullable=False)  # e.g. 'inactive_user', 'service_expiry'
    is_enabled = Column(Integer, server_default=stext("0"))
    hours = Column(Integer, server_default=stext("24"))
    message = Column(Text, server_default=stext("''"))
    buttons_json = Column(Text, server_default=stext("'[]'"))  # JSON array of enabled button keys
    variables = Column(Text, server_default=stext("''"))  # comma-separated var names for admin hint
    info = Column(Text, server_default=stext("''"))  # description label for admin panel

    @classmethod
    def get_all(cls):
        session = Session()
        rules = session.query(cls).order_by(cls.id).all()
        session.close()
        return rules

    @classmethod
    def get_by_key(cls, type_key: str):
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        session.close()
        return rule

    @classmethod
    def get_enabled(cls, type_key: str):
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key, is_enabled=1).first()
        session.close()
        return rule

    @classmethod
    def toggle(cls, type_key: str) -> bool:
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        if not rule:
            session.close()
            return False
        rule.is_enabled = 0 if rule.is_enabled else 1
        session.commit()
        val = rule.is_enabled
        session.close()
        return bool(val)

    @classmethod
    def set_hours(cls, type_key: str, hours: int):
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        if rule:
            rule.hours = hours
            session.commit()
        session.close()

    @classmethod
    def set_message(cls, type_key: str, message: str):
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        if rule:
            rule.message = message
            session.commit()
        session.close()

    @classmethod
    def set_buttons(cls, type_key: str, buttons_json: str):
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        if rule:
            rule.buttons_json = buttons_json
            session.commit()
        session.close()

    @classmethod
    def get_enabled_buttons(cls, type_key: str) -> list:
        session = Session()
        rule = session.query(cls).filter_by(type_key=type_key).first()
        session.close()
        if not rule:
            return []
        try:
            return json.loads(rule.buttons_json)
        except Exception:
            return []


class NotificationLog(Base):
    """Track sent notifications to prevent duplicate sends"""

    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    notification_type = Column(String, nullable=False)  # 'inactive_user' or 'service_expiry'
    target_id = Column(Integer, nullable=False, server_default=stext("0"))  # 0 for user-level, service_id for service-level
    sent_at = Column(String, server_default=func.datetime("now"))

    __table_args__ = (
        UniqueConstraint("user_id", "notification_type", "target_id", name="uq_notification"),
    )

    @classmethod
    def has_sent(cls, user_id: int, notification_type: str, target_id: int = 0) -> bool:
        """Check if a notification has already been sent"""
        session = Session()
        exists = (
            session.query(cls)
            .filter_by(user_id=user_id, notification_type=notification_type, target_id=target_id)
            .first()
            is not None
        )
        session.close()
        return exists

    @classmethod
    def mark_sent(cls, user_id: int, notification_type: str, target_id: int = 0):
        """Record that a notification was sent"""
        session = Session()
        entry = cls(user_id=user_id, notification_type=notification_type, target_id=target_id)
        session.add(entry)
        try:
            session.commit()
        except Exception:
            session.rollback()
        session.close()



class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False)
    plan_id = Column(Integer, nullable=False)
    config_id = Column(Integer, nullable=False)
    service_name = Column(String)
    expires_at = Column(String, nullable=False)
    volume_gb = Column(Integer, nullable=False)
    is_active = Column(Integer, server_default=stext("1"))
    created_at = Column(String, server_default=func.datetime("now"))

    @classmethod
    def create(cls, user_id, plan_id, config_id, service_name, expires_at, volume_gb, session):
        service = cls(
            user_id=user_id,
            plan_id=plan_id,
            config_id=config_id,
            service_name=service_name,
            expires_at=expires_at,
            volume_gb=volume_gb,
        )

        session.add(service)
        session.flush()  # populate service.id

        return service

    @classmethod
    def get(cls, service_id: int):
        """
        Fetches a Service object by its ID using a completely new session.
        """
        with Session() as session:
            # SQLAlchemy 2.0+ syntax (Recommended)
            service = session.get(cls, service_id)
            return service



class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    config_id = Column(Integer)
    amount = Column(Integer, nullable=False)
    payment_method = Column(String)
    status = Column(String, server_default=stext("'pending'"))
    receipt_file_id = Column(String)
    channel_message_id = Column(Integer)
    created_at = Column(String, server_default=func.datetime("now"))
    confirmed_at = Column(String)

    @classmethod
    def create(cls, **kwargs):
        with Session() as session:
            obj = cls(**kwargs)
            session.add(obj)
            session.flush()
            session.refresh(obj)
            return obj

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    category = Column(String, server_default=stext("'عمومی'"))
    volume_gb = Column(Integer, nullable=False)
    duration_days = Column(Integer, nullable=False)
    max_devices = Column(Integer, server_default=stext("1"))
    price = Column(Integer, nullable=False)
    # device_type = Column(String, server_default=stext("'all'"))
    is_active = Column(Integer, server_default=stext("1"))
    # ALTER TABLE plans ADD COLUMN connect_to_panel INTEGER DEFAULT 0;
    # connect_to_panel = Column(Integer, server_default=stext("0"))
    # ALTER TABLE plans ADD COLUMN base_gig INTEGER;
    # ALTER TABLE plans ADD COLUMN base_day INTEGER;
    # base_gig = Column(Integer)  # new
    # base_day = Column(Integer)  # new
    low_stock_alert = Column(Integer, server_default=stext("3"))


class CategorySetting(Base):
    """Store category-level settings: base_gig, base_day, connect_to_panel, min_gig, min_day"""
    __tablename__ = "category_settings"

    category = Column(String, primary_key=True)
    host = Column(String, nullable=True)
    token = Column(String, nullable=True)
    group_ids = Column(String, nullable=True)
    base_gig = Column(Integer, nullable=True)
    base_day = Column(Integer, nullable=True)
    connect_to_panel = Column(Integer, server_default=stext("0"))
    min_gig = Column(Integer, nullable=True)
    min_day = Column(Integer, nullable=True)

    @classmethod
    def get(cls, category: str) -> dict:
        """Get category settings, return defaults if not found"""
        session = Session()
        setting = session.query(cls).filter_by(category=category).first()
        session.close()
        if setting:
            return {
                "category": setting.category,
                "base_gig": setting.base_gig,
                "base_day": setting.base_day,
                "host": setting.host,
                "token": setting.token,
                "group_ids": setting.group_ids,
                "connect_to_panel": setting.connect_to_panel or 0,
                "min_gig": setting.min_gig,
                "min_day": setting.min_day,
            }
        # Return defaults
        return {
            "category": category,
            "base_gig": None,
            "base_day": None,
            "host": None,
            "token": None,
            "group_ids": None,
            "connect_to_panel": 0,
            "min_gig": None,
            "min_day": None,
        }

    @classmethod
    def set(cls, category: str, **kwargs) -> bool:
        session = Session()
        try:
            setting = session.query(cls).filter_by(category=category).first()
            if setting:
                for key, value in kwargs.items():
                    if hasattr(setting, key):
                        setattr(setting, key, value)
            else:
                setting = cls(category=category, **kwargs)
                session.add(setting)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logging.error(f"Error setting category settings: {e}")
            return False
        finally:
            session.close()

    @classmethod
    def get_all_categories_with_settings(cls) -> list:
        """Get all categories that have plans, with their settings"""
        session = Session()
        categories = session.query(Plan.category).filter(Plan.is_active == 1).distinct().all()
        result = []
        for cat in categories:
            cat_name = cat[0]
            setting = session.query(cls).filter_by(category=cat_name).first()
            if setting:
                result.append({
                    "category": setting.category,
                    "base_gig": setting.base_gig,
                    "base_day": setting.base_day,
                    "host": setting.host,
                    "token": setting.token,
                    "group_ids": setting.group_ids,
                    "connect_to_panel": setting.connect_to_panel or 0,
                    "min_gig": setting.min_gig,
                    "min_day": setting.min_day,
                })
            else:
                result.append({
                    "category": cat_name,
                    "base_gig": None,
                    "base_day": None,
                    "host": None,
                    "token": None,
                    "group_ids": None,
                    "connect_to_panel": 0,
                    "min_gig": None,
                    "min_day": None,
                })
        session.close()
        return result

    @classmethod
    def delete(cls, category: str) -> bool:
        """Delete category settings"""
        session = Session()
        try:
            session.query(cls).filter_by(category=category).delete()
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False

class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=False)
    config_data = Column(Text, nullable=False)
    # type = Column(String, nullable=True, server_default=stext("'text'"))
    password = Column(String)
    is_used = Column(Integer, server_default=stext("0"))
    assigned_to = Column(Integer)
    assigned_at = Column(String)
    service_name = Column(String)  # NEW: Store service name for VPN Panel configs

    @classmethod
    def get_stock(cls, plan_id: int) -> int:
        with Session() as session:
            stmt = (
                select(func.count())
                .select_from(cls)
                .where(
                    cls.plan_id == plan_id,
                    cls.is_used == 0,
                )
            )
            result = session.execute(stmt)
            return result.scalar() or 0

    @classmethod
    def create(
        cls,
        plan_id: int,
        config_data: str,
        # type: str = "text",
        password: str | None = None,
        is_used: int = 0,
        assigned_to: int | None = None,
        assigned_at: str | None = None,
        service_name: str | None = None,  # NEW parameter
    ):
        """
        Create a new Config entry with all available fields.
        """
        session = Session()
        try:
            obj = cls(
                plan_id=plan_id,
                config_data=config_data,
                # type=type,
                password=password,
                is_used=is_used,
                assigned_to=assigned_to,
                assigned_at=assigned_at,
                service_name=service_name,  # NEW
            )
            session.add(obj)
            session.commit()
            session.refresh(obj)
            return obj
        finally:
            session.close()

    @classmethod
    def get_with_service_name(cls, config_id: int):
        """Get config with its service_name"""
        session = Session()
        try:
            config = session.query(cls).filter_by(id=config_id).first()
            return config
        finally:
            session.close()

    @classmethod
    def get_service_name_for_config(cls, config_id: int) -> str | None:
        """Get service_name for a specific config"""
        session = Session()
        try:
            config = session.query(cls).filter_by(id=config_id).first()
            if not config or config.service_name is None:
                return None
            return str(config.service_name)
        finally:
            session.close()

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    amount = Column(Integer, nullable=False)
    type = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(String, server_default=func.datetime("now"))


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    full_name = Column(String)
    balance = Column(Integer, server_default=stext("0"))
    referred_by = Column(Integer)
    is_partner = Column(Integer, server_default=stext("0"))
    is_banned = Column(Integer, server_default=stext("0"))
    joined_at = Column(String, server_default=func.datetime('now'))

    pays_referral = Column(Integer, server_default=stext("0"))  # 0 = not paid, 1 = paid
    pays_bonus = Column(Integer, server_default=stext("0"))  # 0 = not paid, 1 = paid
    buy_count = Column(Integer, server_default=stext("0"))


    @classmethod
    def get_top_inviters(
        cls,
        start_time: datetime | str,
        end_time: datetime | str | None = None,
        n: int = 10,
        count: bool = False
    ):
        session = Session()
        invited = aliased(cls)

        if isinstance(start_time, str):
            start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")

        if end_time is None:
            end_time = datetime.now()
        elif isinstance(end_time, str):
            end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")

        base_query = (
            session.query(
                cls,
                func.count(invited.id).label("invite_count")
            )
            .join(invited, cls.telegram_id == invited.referred_by)
            .filter(invited.joined_at >= start_time)
            .filter(invited.joined_at <= end_time)
            .filter(invited.pays_bonus == 0)   # <- only unpaid referrals
            .group_by(cls.id)
            .order_by(func.count(invited.id).desc())
        )

        if count:
            return base_query.count()

        if n != -1:
            base_query = base_query.limit(n)

        return base_query.all()
    @classmethod
    def set_pays_referral_true(cls, telegram_id):
        session = Session()
        user = session.query(cls).filter_by(telegram_id=telegram_id).first()
        if user:
            user.pays_referral = 1
            session.commit()
        session.close()

    @classmethod
    def increase_buy_count(cls, telegram_id):
        session = Session()
        user = session.query(cls).filter_by(telegram_id=telegram_id).first()
        if user:
            user.buy_count += 1
            session.commit()
        session.close()

    @classmethod
    def get_by_telegram_id(cls, telegram_id):
        session = Session()
        user = session.query(cls).filter_by(telegram_id=telegram_id).first()
        session.close()
        return user

    @classmethod
    def get_referral_count(cls, user_id):
        session = Session()
        count = session.query(cls).filter_by(referred_by=user_id).count()
        session.close()
        return count

    @classmethod
    def get_referred_users_counts(cls):
        """
        Returns a tuple (total_count, pays_count):
        - total_count: number of users who have a non-null and non-zero referred_by (i.e., have a referrer).
        - pays_count: number of users who have referred_by + pays_referral=1 (i.e., got referral and paid).
        """
        session = Session()
        total_count = session.query(cls).filter(cls.referred_by.isnot(None)).filter(cls.referred_by != 0).count()
        pays_count = session.query(cls).filter(cls.referred_by.isnot(None)).filter(cls.referred_by != 0).filter(cls.pays_referral == 1).count()
        session.close()
        return total_count, pays_count

    @classmethod
    def get_referred_user_count(cls, user_id):
        session = Session()
        total_count = session.query(cls).filter_by(referred_by=user_id).count()
        pays_count = session.query(cls).filter_by(referred_by=user_id).filter(cls.pays_referral == 1).count()
        session.close()
        return total_count, pays_count

    @classmethod
    def get_referral(cls, user_id):
        session = Session()
        count = session.query(cls).filter_by(referred_by=user_id).all()
        session.close()
        return count

    @classmethod
    def get_referral_with_pay_true(cls, user_id):
        """
        Returns a list of User objects who were referred by the given user_id
        and have pays_referral set to 1.
        """
        session = Session()
        users = session.query(cls).filter_by(referred_by=user_id, pays_referral=1).all()
        session.close()
        return users

    @classmethod
    def get_or_create(cls, telegram_id, username=None, full_name=None, referred_by=None, pays_bonus=0):
        session = Session()
        exists = True
        user = session.query(cls).filter_by(telegram_id=telegram_id).first()
        if user is None:
            exists = False
            user = cls(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                referred_by=referred_by,
                pays_bonus=pays_bonus
            )
            session.add(user)
            session.commit()
        session.close()
        return user, exists


    @classmethod
    def charge_wallet(cls, user_id, amount, description="شارژ کیف پول", session=None):
        """
        Charges the user's wallet using SQLAlchemy ORM, and records the transaction.
        If session is provided, uses it (for transaction chaining), otherwise creates a new session.
        """
        should_close = False
        if session is None:
            session = Session()
            should_close = True

        try:
            # Update user's balance
            user = session.query(cls).filter_by(telegram_id=user_id).first()
            if not user:
                raise Exception("User not found")
            user.balance = (user.balance or 0) + abs(amount)

            # Add wallet transaction record
            wallet_txn = WalletTransaction(
                user_id=user_id,
                amount=amount,
                type='charge',
                description=description
            )
            session.add(wallet_txn)

            if should_close:
                session.commit()

        except Exception as e:
            if should_close:
                session.rollback()
            raise e
        finally:
            if should_close:
                session.close()

def init_db():
    # Create all tables if not exist
    Base.metadata.create_all(engine)

    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS button_colors (
        button_key TEXT PRIMARY KEY,
        color TEXT DEFAULT 'normal'   -- normal, red, blue, green
    );

    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT DEFAULT 'عمومی',
        volume_gb INTEGER NOT NULL,
        duration_days INTEGER NOT NULL,
        max_devices INTEGER DEFAULT 1,
        price INTEGER NOT NULL,
        is_active INTEGER DEFAULT 1,
        low_stock_alert INTEGER DEFAULT 3
    );

    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS support_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        channel_message_id INTEGER,
        status TEXT DEFAULT 'open',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS free_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        used_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS free_test_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_data TEXT NOT NULL,
        description TEXT,
        is_used INTEGER DEFAULT 0,
        assigned_to INTEGER,
        assigned_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        role TEXT DEFAULT 'channel',
        is_active INTEGER DEFAULT 1,
        added_by INTEGER,
        added_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS support_replies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        reply_message TEXT NOT NULL,
        reply_by_admin INTEGER,
        sent_to_user INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (ticket_id) REFERENCES support_tickets(id)
    );

    CREATE TABLE IF NOT EXISTS connection_guides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT UNIQUE NOT NULL,
        guide_text TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    INSERT OR IGNORE INTO settings (key, value) VALUES
        ('bot_name', 'VPN Store'),
        ('welcome_text', 'سلام! به ربات فروش VPN خوش اومدی'),
        ('card_number', ''),
        ('card_owner', ''),
        ('automatic_timeout', '15'),

        ('crypto_address', ''),
        ('crypto_network', 'TRX'),
        ('referral_bonus', '30000'),
        ('partner_fee', '10000000'),
        ('support_channel_id', ''),
        ('receipt_channel_id', ''),
        ('receipt_auto_channel_id', ''),
        ('payment_timeout_minutes', '15'),
        ('free_test_config', ''),
        ('free_test_description', 'این یک کانفیگ تست رایگان است'),
        ('msg_buy_intro', 'پلن مورد نظر را انتخاب کنید:'),
        ('msg_plan_desc', ''),
        ('msg_after_receipt', '✅ رسید شما دریافت شد.\nپس از بررسی توسط تیم ما، سرویس شما فعال خواهد شد.'),
        ('msg_config_sent', '🎉 سرویس شما با موفقیت فعال شد!'),
        ('msg_queue_notice', '✅ پرداخت شما تأیید شد.\n⏲ متأسفانه موجودی این پلن به پایان رسیده.\n\nشما نفر {pos} در صف انتظار هستید.\nبه محض تأمین موجودی، اطلاعات سرویس خدمت شما ارسال خواهد شد.'),
        ('msg_config_from_queue', '🎉 اطلاعات سرویس شما آماده شد!\nممنون از صبر و شکیبایی شما 🌺'),
        ('msg_wallet_intro', '——— کیف پول 💰 ———\nموجودی کیف پول شما :'),
        ('msg_wallet_charge_confirm', '💰 {amount} تومان با موفقیت به کیف پول شما اضافه شد.'),
        ('msg_order_confirm', '🎉 سفارش شما با موفقیت ثبت و تأیید شد!\n\n📝 اطلاعات سرویس خدمت شما:'),
        ('msg_support_intro', 'پیام خود را بنویسید:'),
        ('msg_support_sent', '✅ پیام شما به پشتیبانی ارسال شد. به زودی پاسخ خواهید گرفت.'),
        ('msg_connection_intro', '🔗 آموزش اتصال برای کدام نوع سرویس؟'),
        ('msg_config_footer', 'ممنون از انتخاب مجموعه ما 🌺\nتمام تلاشمون رو می‌کنیم تا بهترین سرویس رو خدمت شما داشته باشیم ✨\nدرصورت نیاز به سرویس جدید در خدمتتون هستیم'),
        ('msg_order_cancelled', '❌ سفارش شما لغو شد.\nدرصورت نیاز با پشتیبانی تماس بگیرید.'),
        ('msg_category_header', '📦 سرویس‌های {category}\n\nپلن مورد نظر را انتخاب کنید:'),
        ('msg_support_intro', 'اگر مشکلی در اتصال، پرداخت یا هر موضوع دیگری دارید، ادمین‌های ما آنلاین هستند 📞\n\nپیام خود را اینجا بنویسید تا سریع‌تر پاسخ دریافت کنید 🌺'),
        ('msg_payment_card', '——— پرداخت کارت به کارت 💳 ———\n\nلطفاً مبلغ زیر را به حساب واریز کنید:\n\n💳 شماره کارت:\n{card}\n👤 به نام: {owner}\n\n💵 مبلغ واریزی: {amount} تومان\n\n❗️ لطفاً از حساب دیگران واریز نکنید\n\n📸 پس از واریز، تصویر رسید را ارسال کنید:'),
        ('msg_payment_crypto', '——— پرداخت ارز دیجیتال 🪙 ———\n\n🌐 شبکه: {network}\n📝 آدرس:\n{address}\n\n💵 مبلغ معادل: {amount} تومان\n\n📸 پس از انتقال، تصویر تراکنش را ارسال کنید:'),
        ('msg_wallet_payment_card', '——— شارژ کیف پول — کارت به کارت 💳 ———\n\n💳 شماره کارت:\n{card}\n👤 به نام: {owner}\n\n💵 مبلغ واریزی: {amount} تومان\n\n❗️ لطفاً از حساب دیگران واریز نکنید\n\n📸 تصویر رسید واریز را ارسال کنید:'),
        ('msg_wallet_payment_crypto', '——— شارژ کیف پول — ارز دیجیتال 🪙 ———\n\n🌐 شبکه: {network}\n📝 آدرس:\n{address}\n\n💵 مبلغ معادل: {amount} تومان\n\n📸 تصویر تراکنش را ارسال کنید:'),
        ('msg_mandatory_channels', 'برای ادامه درکانال های زیر عضو شوید:'),

        ('msg_my_referral_view', 'دعوت شده‌اید\n\n👥 تعداد دعوت شده: {total}\n✅ تعداد خریداری کنند: {pays}'),
        ('msg_no_free_test', 'کانفیگ رایگان توسط ادمین برای شما ارسال میشه'),
        ('msg_free_test_intro', 'لینک: {link} \nتعداد دعوت: {count}'),
        ('msg_free_test_intro', 'لینک: {link} \nتعداد دعوت: {count}'),
        ('msg_bonus', 'هدیه {amount}'),
        ('threash_hold_referrer', '1'),
        ('msg_no_tornoment', '❌ هیچ تورنومنت فعلی در حال اجرا نیست.'),
        ('msg_reach_referral', 'کانفیگ رایگان شما {config}');
    """)

    # Migrations — run safely one by one
    for migration in [
        "ALTER TABLE category_settings ADD COLUMN host TEXT",
        "ALTER TABLE category_settings ADD COLUMN token TEXT",
        "ALTER TABLE category_settings ADD COLUMN group_ids TEXT",
        "ALTER TABLE admin_users ADD COLUMN role TEXT DEFAULT 'channel'",
        "ALTER TABLE configs ADD COLUMN service_name TEXT",

        "ALTER TABLE plans ADD COLUMN category TEXT DEFAULT 'عمومی'",
        "ALTER TABLE services ADD COLUMN service_name TEXT",
        "ALTER TABLE plans ADD COLUMN custom_label TEXT",
        "ALTER TABLE plans ADD COLUMN custom_description TEXT",
        # پلن‌های عمومی همکار — partner_id=NULL یعنی برای همه همکارها قابل استفاده
        """CREATE TABLE IF NOT EXISTS partner_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'عمومی',
            volume_gb INTEGER DEFAULT 1,
            duration_days INTEGER DEFAULT 30,
            max_devices INTEGER DEFAULT 5,
            price INTEGER DEFAULT 0,
            cost INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "ALTER TABLE partner_plans ADD COLUMN cost INTEGER DEFAULT 0",
        "ALTER TABLE configs_partners ADD COLUMN cost INTEGER DEFAULT 0",
        # rebuild جدول partner_plans برای برداشتن NOT NULL از partner_id
        """CREATE TABLE IF NOT EXISTS partner_plans_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER,
            name TEXT NOT NULL,
            category TEXT DEFAULT 'عمومی',
            volume_gb INTEGER DEFAULT 1,
            duration_days INTEGER DEFAULT 30,
            max_devices INTEGER DEFAULT 5,
            price INTEGER DEFAULT 0,
            cost INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        "INSERT OR IGNORE INTO partner_plans_new SELECT id, partner_id, name, category, volume_gb, duration_days, max_devices, price, COALESCE(cost,0), is_active, created_at FROM partner_plans",
        "DROP TABLE IF EXISTS partner_plans_old",
        "ALTER TABLE partner_plans RENAME TO partner_plans_old",
        "ALTER TABLE partner_plans_new RENAME TO partner_plans",
        "DROP TABLE IF EXISTS partner_plans_old",
        "ALTER TABLE configs_partners ADD COLUMN cost INTEGER DEFAULT 0",
        "CREATE TABLE IF NOT EXISTS pending_free_configs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, fulfilled_at TEXT, created_at TEXT DEFAULT (datetime('now')))",
        "CREATE TABLE IF NOT EXISTS pending_configs (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, user_id INTEGER NOT NULL, plan_id INTEGER NOT NULL, amount INTEGER DEFAULT 0, fulfilled_at TEXT, created_at TEXT DEFAULT (datetime('now')))",
        "CREATE TABLE IF NOT EXISTS connection_guides (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT UNIQUE NOT NULL, guide_text TEXT NOT NULL, updated_at TEXT DEFAULT (datetime('now')))",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_charge_confirm', '💰 {amount} تومان با موفقیت به کیف پول شما اضافه شد.')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_order_confirm', '🎉 سفارش شما با موفقیت ثبت و تأیید شد!\n\n📝 اطلاعات سرویس خدمت شما:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_config_footer', 'ممنون از انتخاب مجموعه ما 🌺\nتمام تلاشمون رو می‌کنیم تا بهترین سرویس رو خدمت شما داشته باشیم ✨\nدرصورت نیاز به سرویس جدید در خدمتتون هستیم')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_order_cancelled', '❌ سفارش شما لغو شد.\nدرصورت نیاز با پشتیبانی تماس بگیرید.')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_support_intro', 'اگر مشکلی در اتصال، پرداخت یا هر موضوع دیگری دارید، ادمین‌های ما آنلاین هستند 📞\n\nپیام خود را اینجا بنویسید تا سریع‌تر پاسخ دریافت کنید 🌺')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_payment_card', '——— پرداخت کارت به کارت 💳 ———\n\nلطفاً مبلغ زیر را به حساب واریز کنید:\n\n💳 شماره کارت:\n{card}\n👤 به نام: {owner}\n\n💵 مبلغ واریزی: {amount} تومان\n\n❗️ لطفاً از حساب دیگران واریز نکنید\n\n📸 پس از واریز، تصویر رسید را ارسال کنید:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_payment_crypto', '——— پرداخت ارز دیجیتال 🪙 ———\n\n🌐 شبکه: {network}\n📝 آدرس:\n{address}\n\n💵 مبلغ معادل: {amount} تومان\n\n📸 پس از انتقال، تصویر تراکنش را ارسال کنید:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_payment_card', '——— شارژ کیف پول — کارت به کارت 💳 ———\n\n💳 شماره کارت:\n{card}\n👤 به نام: {owner}\n\n💵 مبلغ واریزی: {amount} تومان\n\n❗️ لطفاً از حساب دیگران واریز نکنید\n\n📸 تصویر رسید واریز را ارسال کنید:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_payment_crypto', '——— شارژ کیف پول — ارز دیجیتال 🪙 ———\n\n🌐 شبکه: {network}\n📝 آدرس:\n{address}\n\n💵 مبلغ معادل: {amount} تومان\n\n📸 تصویر تراکنش را ارسال کنید:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_free_test_success', '✅ تست رایگان با موفقیت فعال شد!\n\n🔗 کانفیگ شما:\n<code>{config}</code>\n\nاز دکمه‌های زیر برای مشاهده جزئیات، آموزش اتصال یا خرید اشتراک همین سرویس استفاده کنید.')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_free_test_unavailable', '❌ تست رایگان در حال حاضر غیرفعال است.')",
        # "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_service_message_page_free', '{service_name} | {category} | {db_valume} | {expire} | {days} | {config} | {used_traffic} | {status} | {remaining_gb}')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_payment_card_send_image', 'عکس رسید خود را بفرستید:')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_charge_choose_amount', 'متن شارژ کیف پول')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_insufficient_balance', 'وجودی کیف پول کافی نیست!\nموجودی: {balance} | قیمت: {price}\nلازم: {diff}')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('msg_wallet_charge_auto_fail', '❌ درخواست شارژ کیف پول به صورت اتوماتیک رد شد.\nدرصورت بروز مشکل با پشتیبانی تماس بگیرید.')",
        # دکمه‌های منوی اصلی
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_buy', 'خرید سرویس 🛒')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_free_test', 'تست رایگان 🎁')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_account', 'حساب کاربری 🖥️')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_wallet', 'کیف پول 💰')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_connection', 'نحوه اتصال 📖')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_support', 'پشتیبانی 📞')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_earn', 'همکاری و کسب درآمد 💡')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_admin', 'پنل مدیریت ⚙️')",
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('btn_tornoment', 'مسابقه 🏆')",
    ]:
        try:
            c.execute(migration)
            conn.commit()
        except:
            pass

    conn.commit()
    conn.close()
    print("Database initialized.")

if __name__ == "__main__":
    init_db()
