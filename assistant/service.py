from assistant.model import DeepSeekClient
from assistant.verifier import AnswerVerifier
from contracts import Answer, AskRequest
from knowledge.search import SearchService


class AssistantService:
    def __init__(
        self, search: SearchService, model: DeepSeekClient, verifier: AnswerVerifier
    ) -> None:
        self.search = search
        self.model = model
        self.verifier = verifier

    def ask(self, request: AskRequest) -> Answer:
        """Обработать вопрос и историю без сохранения состояния между вызовами."""
        raise NotImplementedError
