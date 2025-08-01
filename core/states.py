from aiogram.filters import BaseFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram import types
import os

ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(admin_id) for admin_id in ADMIN_IDS_STR.split(',') if admin_id.strip()]

class IsAdminFilter(BaseFilter):
    async def __call__(self, message: types.Message) -> bool:
        return message.from_user.id in ADMIN_IDS

class AdminStates(StatesGroup):
    GIVE_SUB_USERNAME = State()
    REVOKE_SUB_USERNAME = State()
    BROADCAST_AUDIENCE = State()
    BROADCAST_MESSAGE = State()  
    USER_STATS_USERNAME = State()  

class AdminAmbassador(StatesGroup):
    waiting_for_username_to_set = State()
    waiting_for_username_to_revoke = State()

class AnalysisStates(StatesGroup):
    awaiting_front_photo = State()
    awaiting_profile_photo = State()

class ChatStates(StatesGroup):
    chatting = State()
