import axios from "axios";

const api = axios.create({ baseURL: "/" });

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface AskResponse {
  answer: string;
  graph_used: boolean;
}

export interface UploadResponse {
  status: string;
  filename: string;
  message: string;
  entities?: {
    contracts: string[];
    dates: string[];
    amounts: string[];
    organizations: string[];
  };
}

export async function askQuestion(
  question: string,
  role: string
): Promise<AskResponse> {
  const res = await api.post<AskResponse>("/ask", { question, role });
  return res.data;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await api.post<UploadResponse>("/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

export async function checkHealth(): Promise<boolean> {
  try {
    await api.get("/health");
    return true;
  } catch {
    return false;
  }
}
