from typing import Any

from pasarguard import (
    PasarguardAPI,
    Tools,
    UserCreate,
    UserStatus,
)

class PGPanel:
    def __init__(self, username, password, base_url, token, groups):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.groups = groups

    @classmethod
    async def create(cls, username, password, base_url, groups):
        async with PasarguardAPI(base_url=base_url, verify=True, timeout=30.0) as api:
            token = await api.get_token(username, password)

        return cls(username, password, base_url, token, groups)

    async def create_client(self, total_gb=None, expiry_time=None, limit_ip=10, note="", username=None):
        async with PasarguardAPI(base_url=self.base_url, verify=True, timeout=30.0) as api:
            data_limit = Tools.gb(total_gb) if total_gb is not None else None
            expire = Tools.days(expiry_time) if expiry_time is not None else None
            username_prefix = f"T{total_gb}GB" if total_gb is not None else "TInf"
            print(self.groups)
            user = await api.create_user(
                UserCreate(
                    username=username or Tools.random_username(prefix=username_prefix),
                    data_limit=data_limit,
                    expire=expire,
                    status=UserStatus.ACTIVE,
                    note=note,
                    group_ids=self.groups,#["2"], # DEBUGGGGGGGG
                    hwid_limit=limit_ip if limit_ip is not None else None,
                ),
                token=self.token.access_token,
            )

            # IMPORTANT: SET BASE URL IN PANEL
            # user.subscription_url = f"{self.base_url}/{user.subscription_url.lstrip('/')}"

            return user

    async def get_user(self, username):
        async with PasarguardAPI(base_url=self.base_url, verify=True, timeout=30.0) as api:
            return await api.get_user(username, token=self.token.access_token)

    async def get_active_users(self, limit: int = 100000) -> list[dict[str, Any]]:
        """Fetch all active users using Pasarguard's bulk get_users endpoint."""
        active_users: list[dict[str, Any]] = []
        offset = 0

        async with PasarguardAPI(base_url=self.base_url, verify=True, timeout=30.0) as api:
            while True:
                resp = await api.get_users(
                    token=self.token.access_token,
                    # status=UserStatus.ACTIVE,
                    offset=offset,
                    limit=limit,
                )

                batch = resp.users or []
                if not batch:
                    break

                for user in batch:
                    active_users.append(self._to_dict(user))

                offset += len(batch)
                if offset >= (resp.total or 0):
                    break

        return active_users

    async def is_alive(self):
        async with PasarguardAPI(base_url=self.base_url, verify=True, timeout=30.0) as api:
            try:
                self.token = await api.get_token(self.username, self.password)
            except Exception:
                return False

        return True

    async def get_groups(self):
        result = []
        async with PasarguardAPI(base_url=self.base_url, verify=True, timeout=30.0) as api:
            groups = await api.get_all_groups(token=self.token.access_token)
            for group in groups.groups:
                result.append((group.id, group.name))
            return result

    @staticmethod
    def _to_dict(obj):
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
            return obj.model_dump()
        if hasattr(obj, "dict") and callable(getattr(obj, "dict")):
            return obj.dict()

        data = {}
        for key in dir(obj):
            if key.startswith("_"):
                continue
            try:
                value = getattr(obj, key)
            except Exception:
                continue
            if callable(value):
                continue
            data[key] = value
        return data
