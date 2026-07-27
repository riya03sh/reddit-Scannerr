from functools import lru_cache
from supabase import create_client, Client
from config import settings


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
