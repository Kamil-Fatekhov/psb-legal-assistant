from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike

from contracts import Corpus, RetrievalResult, SearchHit, SearchQuery
from knowledge.vector_index import validate_index


class QueryEmbedder(Protocol):
    def embed_query(self, text: str) -> ArrayLike: ...


class SearchService:
    def __init__(
        self, corpus: Corpus, fragment_ids: list[str], vectors: ArrayLike, embeddings: QueryEmbedder
    ) -> None:
        vectors = np.asarray(vectors)
        validate_index(fragment_ids, vectors)
        unknown_ids = set(fragment_ids) - corpus.fragments.keys()
        if unknown_ids:
            raise ValueError(f"В индексе есть ID вне корпуса: {min(unknown_ids)}")

        self.corpus = corpus
        self.fragment_ids = fragment_ids
        self.vectors = vectors
        self.embeddings = embeddings

    def search(self, query: SearchQuery) -> RetrievalResult:
        top_k = query.top_k
        if not isinstance(top_k, int) or top_k < 0:
            raise ValueError("top_k должен быть целым неотрицательным числом")
        if top_k == 0 or not self.fragment_ids:
            return RetrievalResult()
        q_vec = np.asarray(self.embeddings.embed_query(query.text))
        if q_vec.shape != (self.vectors.shape[1],):
            raise ValueError("Размерность вектора запроса не совпадает с индексом")
        scores = []
        for fragment_id, vector in zip(self.fragment_ids, self.vectors):
            score = np.dot(q_vec, vector)
            scores.append((score, fragment_id))

        hits = []
        for _, fragment_id in sorted(scores, key=lambda x: x[0], reverse=True)[:top_k]:
            fragment = self.corpus.fragments[fragment_id]
            hits.append(SearchHit(fragment=fragment, applicability="unknown"))

        return RetrievalResult(hits=hits)
