from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from contracts import Corpus, Fragment


class CorpusIndexer:
    def read(self, source: Path) -> list[Document]:
        if not source.is_dir():
            raise FileNotFoundError(f"Папка базы знаний не найдена: {source}")
        return [
            Document(page_content=path.read_text(encoding="utf-8-sig"), metadata={"source": str(path)})
            for path in sorted(source.rglob("*.txt"))
            if path.is_file()
        ]

    def chunked(self, docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            add_start_index=True,
        )
        return splitter.split_documents(docs)

    def build(self, source: Path) -> Corpus:
        return self.build_documents(self.read(source))

    def build_documents(self, docs: list[Document]) -> Corpus:
        fragments = {}

        for chunk in self.chunked(docs):
            source_file = Path(chunk.metadata["source"])
            document_id = source_file.stem
            start = chunk.metadata["start_index"]
            revision_id = "base"
            fragment_id = f"{document_id}:{revision_id}:{start}"
            if fragment_id in fragments:
                raise ValueError(f"Повторяющийся ID фрагмента {fragment_id} в {source_file}")

            fragment = Fragment(
                fragment_id=fragment_id,
                document_id=document_id,
                revision_id=revision_id,
                title=source_file.stem,
                point=f"Фрагмент с позиции {start}",
                text=chunk.page_content,
            )

            fragments[fragment_id] = fragment

        return Corpus(fragments=fragments)
