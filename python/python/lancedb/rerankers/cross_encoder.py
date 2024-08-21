#  Copyright (c) 2023. LanceDB Developers
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from functools import cached_property
from typing import Union

import pyarrow as pa

from ..util import attempt_import_or_raise
from .base import Reranker


class CrossEncoderReranker(Reranker):
    """
    Reranks the results using a cross encoder model. The cross encoder model is
    used to score the query and each result. The results are then sorted by the score.

    Parameters
    ----------
    model_name : str, default "cross-encoder/ms-marco-TinyBERT-L-6"
        The name of the cross encoder model to use. See the sentence transformers
        documentation for a list of available models.
    column : str, default "text"
        The name of the column to use as input to the cross encoder model.
    device : str, default None
        The device to use for the cross encoder model. If None, will use "cuda"
        if available, otherwise "cpu".
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-TinyBERT-L-6",
        column: str = "text",
        device: Union[str, None] = None,
        return_score="relevance",
    ):
        super().__init__(return_score)
        torch = attempt_import_or_raise("torch")
        self.model_name = model_name
        self.column = column
        self.device = device
        if self.device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"

    @cached_property
    def model(self):
        sbert = attempt_import_or_raise("sentence_transformers")
        # Allows overriding the automatically selected device
        cross_encoder = sbert.CrossEncoder(self.model_name, device=self.device)

        return cross_encoder

    def _rerank(self, result_set: pa.Table, query: str):
        passages = result_set[self.column].to_pylist()
        cross_inp = [[query, passage] for passage in passages]
        cross_scores = self.model.predict(cross_inp)
        result_set = result_set.append_column(
            "_relevance_score", pa.array(cross_scores, type=pa.float32())
        )

        return result_set

    def rerank_hybrid(
        self,
        query: str,
        vector_results: pa.Table,
        fts_results: pa.Table,
    ):
        combined_results = self.merge_results(vector_results, fts_results)
        combined_results = self._rerank(combined_results, query)
        # sort the results by _score
        if self.score == "relevance":
            combined_results = self._keep_relevance_score(combined_results)
        elif self.score == "all":
            raise NotImplementedError(
                "return_score='all' not implemented for CrossEncoderReranker"
            )
        combined_results = combined_results.sort_by(
            [("_relevance_score", "descending")]
        )

        return combined_results

    def rerank_vector(
        self,
        query: str,
        vector_results: pa.Table,
    ):
        vector_results = self._rerank(vector_results, query)
        if self.score == "relevance":
            vector_results = vector_results.drop_columns(["_distance"])

        vector_results = vector_results.sort_by([("_relevance_score", "descending")])
        return vector_results

    def rerank_fts(
        self,
        query: str,
        fts_results: pa.Table,
    ):
        fts_results = self._rerank(fts_results, query)
        if self.score == "relevance":
            fts_results = fts_results.drop_columns(["_score"])

        fts_results = fts_results.sort_by([("_relevance_score", "descending")])
        return fts_results
