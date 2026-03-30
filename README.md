# 🚀 AI-Powered Knowledge Retrieval Platform

> **Where enterprise data meets intelligent reasoning**

---

# 📌 OVERVIEW

CortexFlow AI Platform is an enterprise-grade AI system that enables intelligent querying over large-scale organizational documents using a **Retrieval-Augmented Generation (RAG)** architecture.

The system evolves from a **baseline RAG pipeline (Phase 1)** to an **intelligent enterprise system (Phase 2)** with reasoning, ranking, and performance optimization.

---

# 🚀 PHASE 1 — BASELINE RAG SYSTEM

## 🎯 Objective

* Build a functional document QA system
* Enable querying over enterprise documents
* Establish a scalable pipeline foundation

---

## ⚙️ Core Components

### 🔹 Document Ingestion

* File loading from local directory
* Multi-format parsing using Apache Tika
* Supports PDF, XML, DOCX, TXT

---

### 🔹 Text Processing

* Chunk size: 500
* Overlap: 100
* Preserves context across chunks

---

### 🔹 Embeddings

* Model: BAAI/bge-large-en-v1.5
* 1024-dimensional semantic vectors

---

### 🔹 Vector Database

* Qdrant for vector storage
* Fast similarity search

---

### 🔹 Retrieval

* Semantic search using cosine similarity
* Top-K relevant chunks retrieved

---

### 🔹 LLM Integration

* Cohere Command R7B
* Generates answers using retrieved context

---

## 🏗️ Phase 1 Architecture

```
Documents → Parser → Chunking → Embeddings → Qdrant
                                              ↓
User Query → Embedding → Retrieval → LLM → Answer
```

---

## ✅ Outcome

✔ End-to-end RAG pipeline
✔ Document-based question answering
✔ Modular and scalable system

---

## ⚠️ Limitations

❌ No query understanding
❌ No ranking refinement
❌ No multi-hop reasoning
❌ No caching

---

# 🚀 PHASE 2 — INTELLIGENCE LAYER

## 🎯 Objective

* Improve accuracy and reasoning
* Handle complex queries
* Optimize performance
* Move toward enterprise-level system

---

## ⚙️ Advanced Features

### 🧠 Query Classifier

* Classifies queries into:

  * Fact
  * Summary
  * Analytical
  * Comparison
* Enables dynamic response behavior

---

### 🏆 Re-ranking (Cross Encoder)

* Uses cross-encoder model
* Re-ranks retrieved chunks
* Improves relevance and precision

---

### 🔗 Multi-hop Reasoning

* Splits complex queries
* Retrieves from multiple contexts
* Combines results for better answers

---

### ⚡ Caching Layer

* In-memory cache
* Stores repeated queries
* Provides instant responses

---

### 📊 Explainability

* Shows retrieved chunks
* Shows re-ranked results
* Improves debugging and transparency

---

## 🏗️ Phase 2 Architecture

```
User Query
   ↓
Cache Check ⚡
   ↓
Query Classifier 🧠
   ↓
Multi-hop Retrieval 🔗
   ↓
Re-ranking 🏆
   ↓
LLM (Cohere) 🤖
   ↓
Final Answer 💡
   ↓
Cache Store ⚡
```

---

## ✅ Outcome

✔ Handles multi-part queries
✔ Improved retrieval accuracy
✔ Faster response time
✔ Intelligent decision-making

---

## 🚀 Improvements Over Phase 1

| Feature             | Phase 1 | Phase 2 |
| ------------------- | ------- | ------- |
| Query Understanding | ❌       | ✅       |
| Retrieval Accuracy  | Medium  | High    |
| Multi-hop Reasoning | ❌       | ✅       |
| Caching             | ❌       | ✅       |
| System Intelligence | ❌       | ✅       |

---

# 🛠️ TECH STACK

* Parsing: Apache Tika
* Embeddings: BAAI/bge-large-en-v1.5
* Vector DB: Qdrant
* LLM: Cohere (Command R7B)
* NLP: spaCy
* Re-ranking: Sentence Transformers

---

# 📂 PROJECT STRUCTURE

```
services/
  phase1_pipeline.py
  phase1_rag.py
  phase1_llm.py
  embedding_service.py
  document_parser.py
  query_classifier.py
  reranker.py
  multihop.py
  cache_service.py

core/
  config.py
  database.py

sample_data/
test_rag.py
```

---

# ⚙️ SETUP

## Install dependencies

```
pip install -r requirements.txt
```

## Setup environment variables

Create `.env`:

```
COHERE_API_KEY=your_api_key_here
```

## Run Qdrant

```
docker run -p 6333:6333 qdrant/qdrant
```

## Run project

```
python test_rag.py
```

---

# 🧪 SAMPLE QUERIES

* What is the contract number?
* Summarize this document
* What risks are mentioned?
* What is the contract number and start date?

---

# 🎯 DESIGN PRINCIPLES

* Modular architecture
* Model-agnostic design
* Scalable for enterprise
* Secure API handling (.env)
