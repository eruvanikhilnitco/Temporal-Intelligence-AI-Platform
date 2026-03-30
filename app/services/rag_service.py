from services.phase1_rag import Phase1RAG

rag = Phase1RAG(folder_path="sample_data")




def ask_rag(question: str, role: str):
    return rag.ask(question, user_role=role)