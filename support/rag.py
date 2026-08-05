import os
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from pypdf import PdfReader

# init chromadb
client = chromadb.PersistentClient(path="./chroma_db")

embedding_func = DefaultEmbeddingFunction()

# get or create collection - just like table in db
collection = client.get_or_create_collection(
    name="coolbreeze_docs",
    embedding_function=embedding_func
)


def chunk_text(text, chunk_size=500):
    words = text.split()

    chunks = []
    current_chunk = []
    current_size = 0

    for word in words:
        current_chunk.append(word)
        current_size += len(word) + 1

        if current_size >= chunk_size:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_size = 0

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def load_documents():
    docs_path = "support/documents/"

    documents = []
    ids = []

    for filename in os.listdir(docs_path):
        if filename.endswith(".pdf"):
            reader = PdfReader(os.path.join(docs_path, filename))

            raw_text = ""
            for page in reader.pages:
                raw_text += page.extract_text()

            chunks = chunk_text(raw_text, chunk_size=500)

            for i, chunk in enumerate(chunks):
                documents.append(chunk)
                ids.append(f"{filename}_{i}")

    if documents:
        collection.add(documents=documents, ids=ids)

    print(f"Loaded {len(documents)} chunks into ChromaDb")

# phase 2 - Retrival


def search_knowledge_base(query):
    results = collection.query(query_texts=[query], n_results=3)

    matched_chunks = results["documents"][0]
    if not matched_chunks:
        return "No relevant information found in the company documents."

    return "\n\n".join(matched_chunks)
