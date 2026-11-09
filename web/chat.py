from assistant.service import AssistantService
from contracts import Answer, AskRequest, SourceView
from knowledge.sources import SourceRepository


class ChatController:
    def __init__(self, assistant: AssistantService, sources: SourceRepository) -> None:
        self.assistant = assistant
        self.sources = sources

    def post_message(self, request: AskRequest) -> Answer:
        """Обработчик будущего POST /api/chat."""
        raise NotImplementedError

    def get_source(self, fragment_id: str) -> SourceView:
        """Обработчик будущего GET /api/sources/{fragment_id}."""
        raise NotImplementedError
