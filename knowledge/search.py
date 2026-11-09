from contracts import Corpus, RetrievalResult, SearchQuery


class SearchService:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def search(self, query: SearchQuery) -> RetrievalResult:
        """Найти пункты и определить применимость редакций."""
        raise NotImplementedError
