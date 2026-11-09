from contracts import Corpus, SourceView


class SourceRepository:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def get_source(self, fragment_id: str) -> SourceView:
        """Открыть исходный фрагмент по ID или поднять SourceNotFound."""
        raise NotImplementedError
