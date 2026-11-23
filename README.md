<div align="center">

# 🏛️ Agentic AI Assistant for Administrative Procedures

### *Ask in plain language. Get cited, trustworthy answers about administrative procedures.*

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic-1C3C3C?style=for-the-badge&logo=langchain&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

[🚀 Quick Start](#-8-getting-started) •
[✨ Features](#-2-key-features) •
[🏗️ Architecture](#️-3-system-architecture) •
[📡 API](#-9-api-documentation) •
[📊 Evaluation](#-10-evaluation--performance)

</div>

---

## 📑 Table of Contents

<details>
<summary><b>Click to expand</b></summary>

1. [Overview](#-1-overview)
2. [Key Features](#-2-key-features)
3. [System Architecture](#️-3-system-architecture)
4. [Tech Stack](#️-4-tech-stack)
5. [RAG Pipeline](#-5-rag-pipeline)
6. [Agent Orchestration](#-6-agent-orchestration)
7. [Project Structure](#-7-project-structure)
8. [Getting Started](#-8-getting-started)
9. [API Documentation](#-9-api-documentation)
10. [Evaluation & Performance](#-10-evaluation--performance)
11. [Security & Guardrails](#️-11-security--guardrails)
12. [Demo & Screenshots](#-12-demo--screenshots)
13. [Limitations & Future Work](#-13-limitations--future-work)
14. [License & Author](#-14-license--author)

</details>

---

## 🎯 1. Overview

### 😩 Problem Statement

Administrative procedures are **scattered, complex, and constantly changing**. Citizens and staff often face:

- 📚 Hundreds of legal documents spread across many sources
- 🔍 Keyword search that misses the real intent of a question
- ⏳ Hours wasted finding the right form, fee, or processing time
- ❌ Chatbots that answer confidently but **without evidence**

### 💡 Project Objectives

| 🎯 Objective | 📝 Description |
|---|---|
| **Accurate** | Every answer is grounded in official documents and cites its sources |
| **Fast** | Hybrid retrieval + reranking for relevant results in seconds |
| **Smart** | An agent that understands intent, remembers context, and asks when unsure |
| **Safe** | Role-based access, guardrails, and human review for sensitive cases |
| **Observable** | Full tracing of latency, tokens, cost, and quality |

### 👥 Target Users

| 👤 User | 🔑 Needs |
|---|---|
| 🧑‍💼 **Citizens** | Step-by-step guidance, required documents, fees, deadlines |
| 🏢 **Government staff** | Quick lookup of regulations with exact references |
| ⚖️ **Legal / compliance teams** | Verifiable citations and audit trails |
| 🛠️ **Admins / Developers** | Manage data, users, and monitor system health |

---

## ✨ 2. Key Features

<table>
<tr>
<td width="50%" valign="top">

### 💬 Intelligent Q&A with Citations
Every answer links back to the **exact document, article, and page** it came from, so users can verify it.

### 🔎 Hybrid Search (Vector + BM25)
Combines **semantic understanding** with **exact keyword matching** to catch both meaning and legal terms.

### 🤖 Agentic Workflow with LangGraph
A stateful graph decides when to retrieve, rewrite the query, clarify, or escalate.

</td>
<td width="50%" valign="top">

### 🧠 Conversation Memory
Remembers short-term context and long-term user preferences across sessions.

### 🔐 Role-Based Access Control
Different roles see different documents and features (Citizen, Staff, Admin).

### 📈 AI Observability & Monitoring
Traces every step: retrieval quality, latency (P50/P95), token usage, and cost.

</td>
</tr>
</table>

---

## 🏗️ 3. System Architecture

### 🗺️ High-Level Architecture Diagram

```mermaid
flowchart LR
    U([👤 User]) --> API[⚡ FastAPI Gateway]
    API --> AUTH{🔐 RBAC}
    AUTH --> AGENT[🤖 LangGraph Agent]

    AGENT --> RET[🔎 Hybrid Retriever]
    RET --> VDB[(🧬 Vector DB)]
    RET --> BM25[(📚 BM25 Index)]
    RET --> RR[🎯 Reranker]
    RR --> LLM[🧠 LLM]

    AGENT <--> MEM[(💾 Memory Store)]
    AGENT -.-> HITL[🙋 Human Review]
    LLM --> ANS([✅ Answer + Citations])

    AGENT -.-> OBS[📈 Observability]
    RET -.-> OBS
    LLM -.-> OBS
```

### 🧩 Component Overview

| Component | Role |
|---|---|
| ⚡ **API Layer** | Handles requests, auth, streaming responses |
| 🤖 **Agent Orchestrator** | Routes intent, controls workflow, manages retries |
| 🔎 **Retriever** | Hybrid search across vector and keyword indexes |
| 🎯 **Reranker** | Re-scores candidates for precision |
| 🧠 **Generator** | Produces grounded answers with citations |
| 💾 **Memory** | Stores conversation and user context |
| 📈 **Observability** | Traces, metrics, cost tracking |

### 🔄 Data Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as 👤 User
    participant A as 🤖 Agent
    participant R as 🔎 Retriever
    participant L as 🧠 LLM
    U->>A: Ask a question
    A->>A: Classify intent & load memory
    A->>R: Rewrite query & search (Vector + BM25)
    R-->>A: Top-K reranked passages
    A->>L: Question + context
    L-->>A: Grounded answer
    A-->>U: Answer + 📎 citations
```

---

## 🛠️ 4. Tech Stack

| Layer | Technologies |
|---|---|
| 🧠 **AI & LLM** | `LangGraph` · `LangChain` · LLM provider of choice · Embedding model · Reranker |
| ⚙️ **Backend & API** | `Python` · `FastAPI` · `Pydantic` · `Uvicorn` |
| 🗄️ **Databases & Search** | `PostgreSQL` · Vector DB (e.g. `pgvector` / `Qdrant`) · `BM25` (e.g. `Elasticsearch` / `OpenSearch`) · `Redis` |
| ☁️ **Infrastructure & Monitoring** | `Docker` · `Docker Compose` · `Langfuse` / `LangSmith` · `Prometheus` · `Grafana` |

> 💡 *Swap in your actual choices. The architecture is provider-agnostic.*

---

## 🔬 5. RAG Pipeline

```mermaid
flowchart LR
    A[📥 Ingest] --> B[🧹 Process] --> C[🗂️ Index] --> D[🔎 Retrieve] --> E[🎯 Rerank] --> F[✍️ Generate]
```

### 📥 5.1 Data Ingestion
- 📄 Sources: PDFs, DOCX, HTML pages, official portals
- 🕷️ Crawlers and upload endpoints
- 🏷️ Metadata captured: document ID, issuing authority, effective date, version

### 🧹 5.2 Data Processing & Indexing
- 🔤 Text extraction + OCR for scanned files
- ✂️ **Structure-aware chunking** (by article / clause / section)
- 🧬 Embeddings → vector index
- 📚 Tokenized text → BM25 index
- 🔖 Metadata preserved for filtering and citations

### 🔎 5.3 Hybrid Retrieval
```text
score = α · vector_similarity + (1 − α) · bm25_score
```
- Fusion strategy: **Reciprocal Rank Fusion (RRF)** or weighted sum
- Metadata filters: authority, validity period, role permissions

### 🎯 5.4 Reranking & Generation
- Cross-encoder reranker narrows Top-K to the best passages
- Prompt enforces: *answer only from context, cite every claim, say "I don't know" when unsure*
- Output: ✅ answer · 📎 citations · 📝 suggested next steps

---

## 🤖 6. Agent Orchestration

### 🕸️ 6.1 LangGraph Workflow

```mermaid
stateDiagram-v2
    [*] --> Classify
    Classify --> Chitchat: small talk
    Classify --> Clarify: ambiguous
    Classify --> Retrieve: procedure question
    Clarify --> Classify: user replies
    Retrieve --> Grade
    Grade --> Rewrite: low relevance
    Rewrite --> Retrieve
    Grade --> Generate: good context
    Generate --> Review: sensitive / low confidence
    Generate --> [*]
    Review --> [*]
    Chitchat --> [*]
```

### 🧭 6.2 Intent Classification & Routing

| 🏷️ Intent | ➡️ Route |
|---|---|
| 📋 Procedure lookup | RAG pipeline |
| 💬 Small talk | Direct response |
| ❓ Ambiguous | Ask clarifying question |
| 🚫 Out-of-scope | Polite refusal + guidance |
| ⚠️ Sensitive / high-risk | Human-in-the-loop |

### 🧠 6.3 Memory Management
- ⚡ **Short-term**: recent turns in the conversation window
- 🗃️ **Long-term**: summarized history and user preferences
- 🔒 Memory is scoped per user and respects RBAC

### 🙋 6.4 Human-in-the-Loop
- Triggered by low confidence, sensitive topics, or user request
- Staff can **approve, edit, or reject** a draft before it is sent
- Feedback is logged to improve future evaluation sets

### 🔁 6.5 Error Handling & Retry
- ⏱️ Timeouts with **exponential backoff**
- 🔀 Fallback models and fallback retrieval strategies
- 🛑 Graceful degradation: partial answer + honest uncertainty
- 📝 All failures traced for debugging

---

## 📂 7. Project Structure

```text
📦 agentic-admin-assistant
├── 📁 app
│   ├── 📁 api            # FastAPI routes, schemas, dependencies
│   ├── 📁 agent          # LangGraph nodes, edges, state
│   ├── 📁 rag            # ingestion, chunking, retrieval, reranking
│   ├── 📁 memory         # short/long-term memory
│   ├── 📁 security       # auth, RBAC, guardrails
│   ├── 📁 observability  # tracing, metrics
│   └── 📄 main.py
├── 📁 data               # raw & processed documents
├── 📁 evaluation         # datasets, scripts, reports
├── 📁 tests
├── 📁 docker
├── 📄 .env.example
├── 📄 docker-compose.yml
├── 📄 requirements.txt
└── 📄 README.md
```

---

## 🚀 8. Getting Started

### ✅ 8.1 Prerequisites

- 🐍 Python **3.11+**
- 🐳 Docker & Docker Compose
- 🔑 API key for your LLM provider

### 📦 8.2 Installation

```bash
# 1️⃣ Clone the repository
git clone https://github.com/<your-username>/agentic-admin-assistant.git
cd agentic-admin-assistant

# 2️⃣ Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3️⃣ Install dependencies
pip install -r requirements.txt
```

### 🔧 8.3 Environment Configuration

```bash
cp .env.example .env
```

```env
# 🧠 LLM
LLM_API_KEY=your_api_key
LLM_MODEL=your_model_name

# 🗄️ Database
DATABASE_URL=postgresql://user:password@localhost:5432/admin_assistant

# 🔎 Search
VECTOR_DB_URL=http://localhost:6333
BM25_URL=http://localhost:9200

# 💾 Cache
REDIS_URL=redis://localhost:6379

# 📈 Observability
TRACING_PUBLIC_KEY=your_key
TRACING_SECRET_KEY=your_secret
```

### 🗄️ 8.4 Database Setup

```bash
# Start infrastructure
docker compose up -d

# Run migrations
alembic upgrade head

# Ingest and index documents
python -m app.rag.ingest --source data/raw
```

### ▶️ 8.5 Running the Application

```bash
uvicorn app.main:app --reload --port 8000
```

| 🔗 Service | URL |
|---|---|
| 🌐 API | http://localhost:8000 |
| 📘 Swagger Docs | http://localhost:8000/docs |
| 📈 Dashboards | http://localhost:3000 |

---

## 📡 9. API Documentation

| Method | Endpoint | Description | 🔐 Role |
|:---:|---|---|:---:|
| `POST` | `/api/v1/chat` | Ask a question, get answer + citations | User |
| `POST` | `/api/v1/chat/stream` | Streaming response (SSE) | User |
| `GET` | `/api/v1/conversations/{id}` | Retrieve conversation history | User |
| `POST` | `/api/v1/documents` | Upload and index a document | Admin |
| `GET` | `/api/v1/reviews` | List pending human reviews | Staff |
| `POST` | `/api/v1/reviews/{id}` | Approve / edit / reject | Staff |
| `GET` | `/health` | Health check | Public |

<details>
<summary><b>📨 Example request & response</b></summary>

**Request**
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "abc-123",
    "message": "What documents do I need to renew my ID card?"
  }'
```

**Response**
```json
{
  "answer": "You need to prepare the following documents: ...",
  "citations": [
    {
      "document": "Decree XX/20XX",
      "section": "Article 12",
      "page": 5,
      "score": 0.91
    }
  ],
  "confidence": 0.88,
  "needs_review": false
}
```

</details>

---

## 📊 10. Evaluation & Performance

> 📌 *Fill in the numbers after running your evaluation scripts.*

### 🔎 10.1 Retrieval Evaluation

| Metric | Vector only | BM25 only | **Hybrid** | **Hybrid + Rerank** |
|---|:---:|:---:|:---:|:---:|
| Recall@5 | TBD | TBD | TBD | TBD |
| MRR | TBD | TBD | TBD | TBD |
| nDCG@10 | TBD | TBD | TBD | TBD |

### 🤖 10.2 Agent Evaluation

| Metric | Score |
|---|:---:|
| ✅ Answer correctness | TBD |
| 📎 Citation accuracy | TBD |
| 🎯 Faithfulness (no hallucination) | TBD |
| 🧭 Intent routing accuracy | TBD |

### ⏱️ 10.3 Latency (P50/P95)

| Stage | P50 | P95 |
|---|:---:|:---:|
| Retrieval | TBD | TBD |
| Reranking | TBD | TBD |
| Generation | TBD | TBD |
| **End-to-end** | **TBD** | **TBD** |

### 💰 10.4 Token Usage & Cost

| Metric | Avg per query |
|---|:---:|
| 🔤 Input tokens | TBD |
| 🔡 Output tokens | TBD |
| 💵 Estimated cost | TBD |

---

## 🛡️ 11. Security & Guardrails

| 🛡️ Layer | 🔒 Protection |
|---|---|
| **Authentication** | JWT / OAuth2 |
| **Authorization** | Role-based access to documents and endpoints |
| **Input guardrails** | Prompt-injection detection, PII masking |
| **Output guardrails** | Citation enforcement, hallucination checks, refusal of out-of-scope requests |
| **Data protection** | Encrypted secrets, scoped memory, audit logs |
| **Human oversight** | Escalation for sensitive or low-confidence answers |

---

## 🎬 12. Demo & Screenshots

<div align="center">

| 💬 Chat with Citations | 🙋 Human Review | 📈 Monitoring Dashboard |
|:---:|:---:|:---:|
| ![chat](docs/images/chat.png) | ![review](docs/images/review.png) | ![dashboard](docs/images/dashboard.png) |

🎥 **Demo video:** [Watch here](#)

</div>

---

## 🔭 13. Limitations & Future Work

### ⚠️ Current Limitations
- 📅 Answers depend on how up-to-date the indexed documents are
- 🌐 Limited to the supported domains and languages
- 🧾 Complex multi-step cases may still need human review

### 🗺️ Roadmap
- [x] Hybrid retrieval with reranking
- [x] Agent workflow with memory
- [ ] 🔄 Automatic document update detection
- [ ] 🌍 Multilingual support
- [ ] 📝 Auto-fill forms from conversation
- [ ] 📱 Mobile / chat-platform integrations
- [ ] 🧪 Continuous evaluation pipeline

---

## 📜 14. License & Author

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

<div align="center">

### 👨‍💻 Author

**Your Name**
[![GitHub](https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/your-username)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white)](https://linkedin.com/in/your-profile)
[![Email](https://img.shields.io/badge/Email-D14836?style=flat-square&logo=gmail&logoColor=white)](mailto:you@example.com)

---

⭐ **If you find this project useful, please give it a star!** ⭐

</div>
