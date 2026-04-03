"""Pydantic request/response schemas — one file per domain.

Import all schemas here for convenient access:
    from backend.openloop.api.schemas import SpaceCreate, SpaceResponse, ...
"""

from backend.openloop.api.schemas.agents import *  # noqa: F401, F403
from backend.openloop.api.schemas.approvals import *  # noqa: F401, F403
from backend.openloop.api.schemas.autonomous import *  # noqa: F401, F403
from backend.openloop.api.schemas.audit import *  # noqa: F401, F403
from backend.openloop.api.schemas.automations import *  # noqa: F401, F403
from backend.openloop.api.schemas.behavioral_rules import *  # noqa: F401, F403
from backend.openloop.api.schemas.conversations import *  # noqa: F401, F403
from backend.openloop.api.schemas.data_sources import *  # noqa: F401, F403
from backend.openloop.api.schemas.documents import *  # noqa: F401, F403
from backend.openloop.api.schemas.drive import *  # noqa: F401, F403
from backend.openloop.api.schemas.home import *  # noqa: F401, F403
from backend.openloop.api.schemas.items import *  # noqa: F401, F403
from backend.openloop.api.schemas.memory import *  # noqa: F401, F403
from backend.openloop.api.schemas.notifications import *  # noqa: F401, F403
from backend.openloop.api.schemas.odin import *  # noqa: F401, F403
from backend.openloop.api.schemas.search import *  # noqa: F401, F403
from backend.openloop.api.schemas.spaces import *  # noqa: F401, F403
from backend.openloop.api.schemas.stats import *  # noqa: F401, F403
from backend.openloop.api.schemas.system import *  # noqa: F401, F403
from backend.openloop.api.schemas.widgets import *  # noqa: F401, F403
