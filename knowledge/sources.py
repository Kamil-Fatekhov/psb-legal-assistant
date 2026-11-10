from contracts import Corpus, SourceNotFound, SourceView


class SourceRepository:
    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def get_source(self, fragment_id: str) -> SourceView:
        """Открыть исходный фрагмент по ID или поднять SourceNotFound."""
        fragment = self.corpus.fragments.get(fragment_id)
        if fragment is None:
            raise SourceNotFound(fragment_id)
        return SourceView(fragment=fragment, context_text=fragment.text)
