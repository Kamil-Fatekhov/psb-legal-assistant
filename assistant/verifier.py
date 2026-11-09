from contracts import Answer, RetrievalResult


class AnswerVerifier:
    def verify(self, draft: Answer, evidence: RetrievalResult) -> Answer:
        """Проверить выводы и ссылки перед выдачей ответа."""
        raise NotImplementedError
