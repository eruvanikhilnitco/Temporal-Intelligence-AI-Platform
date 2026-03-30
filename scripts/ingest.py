from services.phase1_rag import Phase1RAG

rag = Phase1RAG(folder_path="sample_data")

rag.ingest()

print("✅ Ingestion completed successfully")