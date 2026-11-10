from pathlib import Path

import numpy as np
import torch
from langchain_huggingface import HuggingFaceEmbeddings

from knowledge.indexer import CorpusIndexer

device = "cuda" if torch.cuda.is_available() else "cpu"
indexer = CorpusIndexer()
corpus = indexer.build(Path("knowledge-base"))
embeddings = HuggingFaceEmbeddings(
    model_name="BAAI/bge-m3",
    model_kwargs={"device": device},
    encode_kwargs={"normalize_embeddings": True}
)

print(device)
scores = []
fragments = corpus.fragments
q_vec = embeddings.embed_query("До какого числа платить за склад?")
c_vec = embeddings.embed_documents([fragment.text for fragment in fragments.values()])
for idx, fragment in enumerate(fragments.values()):
    score = np.dot(q_vec, c_vec[idx])
    scores.append((score, fragment.fragment_id))

for score, fragment_id in sorted(scores, key=lambda x: x[0], reverse=True)[:5]:
    print(score, fragment_id, fragments[fragment_id].text[:100])
