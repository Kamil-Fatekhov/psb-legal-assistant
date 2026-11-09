from contracts import Answer, AskRequest, RetrievalResult


class DeepSeekClient:
    def draft(self, request: AskRequest, evidence: RetrievalResult) -> Answer:
        """Получить черновик ответа по предоставленным фрагментам."""
        raise NotImplementedError
