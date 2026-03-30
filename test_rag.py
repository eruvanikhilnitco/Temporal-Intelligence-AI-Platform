from services.phase1_rag import Phase1RAG

rag = Phase1RAG(folder_path="sample_data")

# Step 1: ingest (run once)
rag.ingest()

print("\n🚀 CortexFlow AI Ready!")
print("Type 'exit' to quit\n")

while True:
    question = input("👉 Enter your question: ")

    if question.lower() == "exit":
        print("\n👋 Exiting... Goodbye!\n")
        break

    if not question.strip():
        print("⚠️ Please enter a valid question\n")
        continue

    # 🧠 Query classification
    query_type = rag.classifier.classify(question)
    print(f"\n🧠 Query Type: {query_type}")

    # 📄 Step 1: Retrieve (Top 10)
    retrieved = rag.query(question)

    print("\n📄 Retrieved Context (Before Re-ranking):\n")
    for i, c in enumerate(retrieved):
        print(f"{i+1}. {c[:120]}...\n")

    # 🔥 Step 2: Re-rank (Top 3)
    reranked = rag.reranker.rerank(question, retrieved)

    print("\n🏆 Top Context (After Re-ranking):\n")
    for i, c in enumerate(reranked):
        print(f"{i+1}. {c[:150]}...\n")

    # 💡 Step 3: Final Answer (uses reranked internally via ask())
    answer = rag.ask(question)

    print("\n💡 Final Answer:\n")
    print(answer)

    print("\n" + "="*60 + "\n")