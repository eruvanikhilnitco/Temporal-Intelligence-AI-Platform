from services.phase1_rag import Phase1RAG

rag = Phase1RAG(folder_path="sample_data")

# Step 1: ingest (run once)
rag.ingest()

print("\n🚀 CortexFlow AI Ready!")
print("Type 'exit' to quit\n")

# 🔥 dynamic roles
valid_roles = ["public", "user", "admin"]

while True:
    user_role = input("🔐 Enter your role (public/user/admin): ").strip().lower()

    if user_role in valid_roles:
        break
    else:
        print("⚠️ Invalid role. Choose from public/user/admin\n")

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

    # 📄 Step 1: Retrieve (RBAC applied)
    retrieved = rag.query(question, user_role=user_role)

    if not retrieved:
        print("\n🚫 No accessible data found for your role.\n")
        continue

    print("\n📄 Retrieved Context (Before Re-ranking):\n")
    for i, c in enumerate(retrieved):
        print(f"{i+1}. {c[:120]}...\n")

    # 🏆 Step 2: Re-rank
    reranked = rag.reranker.rerank(question, retrieved)

    print("\n🏆 Top Context (After Re-ranking):\n")
    for i, c in enumerate(reranked):
        print(f"{i+1}. {c[:150]}...\n")

    # 💡 Step 3: Final Answer (RBAC + caching inside)
    answer = rag.ask(question, user_role=user_role)

    print("\n💡 Final Answer:\n")
    print(answer)

    print("\n" + "="*60 + "\n")