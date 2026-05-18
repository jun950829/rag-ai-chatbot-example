"""앱 전역 ORM 진입점.

도메인별 정의는 ``app.models.company`` / ``app.models.product`` / ``app.models.kprint`` 아래에 두고,
여기서는 Alembic·메타데이터 로드를 위해 모든 테이블 클래스를 한 번에 import 한다.
"""

from app.db.models.conversation_session import ConversationSession
from app.db.models.message import Message
from app.db.models.message_meta import MessageMeta
from app.models.company.models import Company
from app.models.kprint.catalog import KprintExhibitItem, KprintExhibitor
from app.models.kprint.qa_quickmenu import KprintQaQuickmenu
from app.models.product.models import Product

__all__ = [
    "Company",
    "ConversationSession",
    "KprintExhibitItem",
    "KprintExhibitor",
    "KprintQaQuickmenu",
    "Message",
    "MessageMeta",
    "Product",
]
