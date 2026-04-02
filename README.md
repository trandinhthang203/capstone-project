# capstone-project

```CAPSTONE-PROJECT/
│
├── .env                          # API keys, config — KHÔNG commit
├── .env.example                  # Template .env — commit cái này
├── .gitignore
├── README.md
├── requirements.txt
├── docker-compose.yml            # Orchestrate toàn bộ services
│
├── notebooks/                    # Giữ nguyên — EDA, experiments
│   ├── 01_data_exploration.ipynb
│   ├── 02_rag_experiments.ipynb
│   └── 03_chunking_eval.ipynb
│
├── data/                         # Dữ liệu raw + processed
│   ├── raw/                      # File crawl từ dichvucong — không commit (gitignore)
│   ├── processed/                # JSON đã clean + normalize
│   └── evaluation/               # Test set câu hỏi để đánh giá
│       ├── test_queries.json
│       └── ground_truth.json
│
├── forms/                        # Mẫu đơn — không commit file gốc
│   ├── originals/                # File .doc/.docx gốc từ dichvucong
│   ├── templates/                # Template đã gắn {{placeholder}}
│   │   ├── CT01/
│   │   │   ├── template.docx
│   │   │   ├── fields.json
│   │   │   └── preview.png
│   │   └── HKD01/
│   │       ├── template.docx
│   │       ├── fields.json
│   │       └── preview.png
│   └── outputs/                  # PDF tạm — gitignore, xóa sau 1h
│
├── scripts/                      # Script chạy một lần — crawl, embed, setup
│   ├── crawl_dichvucong.py       # Crawl thủ tục từ dichvucong.gov.vn
│   ├── process_forms.py          # Pipeline xử lý mẫu đơn (Vision AI + review)
│   ├── build_vectordb.py         # Chunk + embed + upsert vào Qdrant
│   ├── seed_database.py          # Insert dữ liệu vào PostgreSQL
│   └── evaluate.py               # Chạy evaluation + ablation study
│
├── backend/                      # FastAPI + LangGraph
│   ├── Dockerfile
│   ├── config.py                 # Tất cả đường dẫn + settings tập trung đây
│   ├── main.py                   # FastAPI app entry point
│   ├── dependencies.py           # Dependency injection (DB, Redis, Storage)
│   │
│   ├── agents/                   # LangGraph nodes — mỗi file = 1 agent
│   │   ├── __init__.py
│   │   ├── graph.py              # StateGraph definition + conditional edges
│   │   ├── state.py              # GraphState TypedDict
│   │   ├── intent_node.py
│   │   ├── retrieval_node.py
│   │   ├── form_id_node.py
│   │   ├── info_check_node.py
│   │   ├── info_collector_node.py
│   │   ├── form_fill_node.py
│   │   └── utility/
│   │       ├── location_node.py
│   │       ├── deadline_node.py
│   │       ├── progress_tracker_node.py
│   │       └── fee_calculator_node.py
│   │
│   ├── mcp_servers/              # MCP server layer
│   │   ├── vector_db_server.py   # Wrap Qdrant
│   │   ├── form_db_server.py     # Wrap PostgreSQL form queries
│   │   ├── maps_server.py        # Wrap Google Places API
│   │   └── fee_server.py         # Wrap fee calculation logic
│   │
│   ├── api/                      # FastAPI routers
│   │   ├── __init__.py
│   │   ├── chat.py               # POST /chat, GET /chat/stream (SSE)
│   │   ├── forms.py              # POST /forms/fill, GET /forms/{code}/fields
│   │   └── health.py             # GET /health
│   │
│   ├── services/                 # Business logic tách khỏi agents
│   │   ├── rag_service.py        # RAG pipeline
│   │   ├── form_service.py       # fill_form(), get_fields()
│   │   ├── voice_service.py      # STT (Whisper) + TTS (FPT)
│   │   └── pdf_service.py        # WeasyPrint render
│   │
│   ├── db/                       # Database layer
│   │   ├── postgres.py           # SQLAlchemy models + connection
│   │   ├── qdrant.py             # Qdrant client + search functions
│   │   └── redis.py              # Redis client + session management
│   │
│   └── storage/                  # Storage abstraction (local vs S3)
│       ├── __init__.py           # get_storage() factory function
│       ├── local_storage.py
│       └── s3_storage.py
│
├── frontend/                     # React + TypeScript
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── Chat/
│       │   │   ├── ChatWindow.tsx
│       │   │   ├── MessageBubble.tsx
│       │   │   ├── VoiceInput.tsx    # Mic button + Web Audio API
│       │   │   └── AgentTrace.tsx    # Hiển thị agent đang chạy
│       │   ├── Forms/
│       │   │   ├── ChecklistCard.tsx
│       │   │   └── PDFDownload.tsx
│       │   └── Map/
│       │       └── LocationMap.tsx   # Google Maps embed
│       ├── hooks/
│       │   ├── useChat.ts            # SSE streaming logic
│       │   └── useVoice.ts           # MediaRecorder + Whisper
│       ├── services/
│       │   └── api.ts                # Axios calls đến backend
│       └── types/
│           └── index.ts              # TypeScript interfaces
│
└── nginx/
    └── nginx.conf                # Reverse proxy config
```