
eval_questions = [
    "Can you provide a concise description of the TinyLlama model?",
    "I would like to know the speed optimizations that TinyLlama has made.",
    "Why TinyLlama uses Grouped-query Attention?",
    "Is the TinyLlama model open source?",
    "Tell me about starcoderdata dataset",
]

ground_truths = [
    "TinyLlama is a compact 1.1B language model pretrained on around 1 trillion tokens for approximately 3 epochs. It builds on Llama 2 architecture and significantly outperforms existing open-source models of comparable size.",
    "TinyLlama integrates FSDP for multi-GPU training, Flash Attention for optimized attention computation, and a fused SwiGLU module, reducing memory footprint so the 1.1B model fits within 40GB GPU RAM.",
    "TinyLlama uses Grouped-query Attention to reduce memory bandwidth overhead and speed up inference. It uses 32 heads for query attention and 4 groups of key-value heads, sharing representations across heads without sacrificing much performance.",
    "Yes, TinyLlama is open-source.",
    "The StarCoderData dataset was collected to train StarCoder. It contains approximately 250 billion tokens across 86 programming languages, and also includes GitHub issues and text-code pairs involving natural languages.",
]

mock_answers = [
    "TinyLlama is a 1.1B parameter language model trained on 1 trillion tokens. It uses the Llama 2 architecture and tokenizer, and achieves strong performance on downstream tasks despite its small size.",
    "TinyLlama uses Flash Attention and FSDP to speed up training. It also uses SwiGLU activation. These optimizations allow it to fit within 40GB of GPU memory.",
    "Grouped-query Attention is used to reduce memory bandwidth and speed up inference. The model has 32 query heads and 4 key-value head groups.",
    "Yes, TinyLlama is fully open-source and available on GitHub.",
    "StarCoderData contains code from 86 programming languages and about 250 billion tokens. It was used to train the StarCoder model and includes GitHub issues as well.",
]

mock_contexts = [
    [
        "TinyLlama is a 1.1B language model pretrained on approximately 1 trillion tokens for around 3 epochs. It adopts the architecture and tokenizer of Llama 2.",
        "Despite its relatively small size, TinyLlama significantly outperforms existing open-source language models with comparable sizes on a series of downstream tasks.",
        "TinyLlama leverages various advances contributed by the open-source community, including FlashAttention, achieving better computational efficiency.",
    ],
    [
        "During training, the codebase has integrated FSDP to leverage multi-GPU and multi-node setups efficiently.",
        "Another critical improvement is the integration of Flash Attention, an optimized attention mechanism that reduces memory footprint.",
        "We replaced the fused SwiGLU module from xFormers with the original SwiGLU module, enabling the 1.1B model to fit within 40GB of GPU RAM.",
    ],
    [
        "To reduce memory bandwidth overhead and speed up inference, TinyLlama uses grouped-query attention.",
        "The model has 32 heads for query attention and uses 4 groups of key-value heads.",
        "With this technique, the model can share key and value representations across multiple heads without sacrificing much performance.",
    ],
    [
        "TinyLlama is an open-source project. The code and model weights are publicly available.",
        "The project aims to provide the community with a compact yet capable language model.",
        "TinyLlama follows the Llama 2 architecture and is released under an open-source license.",
    ],
    [
        "The StarCoderData dataset was collected to train StarCoder, a powerful open-source large code language model.",
        "It comprises approximately 250 billion tokens across 86 programming languages.",
        "In addition to code, it also includes GitHub issues and text-code pairs that involve natural languages.",
    ],
]
# import os
# os.environ["OPENAI_API_KEY"] = "dummy"

from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas import evaluate
from datasets import Dataset
from langchain_huggingface import HuggingFaceEmbeddings
from app.helpers.utils.common import _llm

ragas_llm = LangchainLLMWrapper(_llm)

ragas_embeddings = LangchainEmbeddingsWrapper(
    HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
)

faithfulness.llm = ragas_llm
answer_relevancy.llm = ragas_llm
answer_relevancy.embeddings = ragas_embeddings
context_recall.llm = ragas_llm
context_precision.llm = ragas_llm

data = {
    "question": eval_questions,
    "answer": mock_answers,      
    "contexts": mock_contexts,   
    "ground_truth": ground_truths,
}

dataset = Dataset.from_dict(data)

metrics = [faithfulness, answer_relevancy, context_recall, context_precision]

result = evaluate(
    dataset,
    metrics=metrics,
    embeddings=ragas_embeddings,  
)

result.to_pandas().to_csv("mock_eval_result.csv", index=False)
print(result)