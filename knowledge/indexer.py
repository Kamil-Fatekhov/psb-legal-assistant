from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from contracts import Corpus, Fragment


class CorpusIndexer:
    def read(self, source: Path) -> list[Document]:
        loader = DirectoryLoader(
            path=str(source),
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
            show_progress=True,
        )
        return loader.load()

    def chunked(self, docs: list[Document]) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            add_start_index=True,
        )
        return splitter.split_documents(docs)

    def build(self, source: Path) -> Corpus:
        """Загрузить папку с TXT и собрать каталог фрагментов."""
        docs = self.read(source)
        print(len(docs))
        chunks = self.chunked(docs)
        print(len(chunks))
        fragments = {}

        for chunk in chunks:
            source_file = Path(chunk.metadata["source"])
            document_id = source_file.stem
            start = chunk.metadata["start_index"]
            revision_id = "base"
            fragment_id = f"{document_id}:{revision_id}:{start}"

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
