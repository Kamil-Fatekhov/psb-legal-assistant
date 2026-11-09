from pathlib import Path

from contracts import Corpus


class CorpusIndexer:
    def build(self, source: Path) -> Corpus:
        """Загрузить папку или ZIP и собрать каталог пунктов."""
        raise NotImplementedError
