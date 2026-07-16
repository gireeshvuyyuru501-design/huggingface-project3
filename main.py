import os
import time

import streamlit as st
from dotenv import load_dotenv

try:
    from langchain_groq import ChatGroq
except Exception as exc:
    ChatGroq = None
    CHAT_GROQ_IMPORT_ERROR = exc

try:
    from langchain_openai import OpenAIEmbeddings
except Exception as exc:
    OpenAIEmbeddings = None
    OPENAI_IMPORT_ERROR = exc

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception as exc:
    HuggingFaceEmbeddings = None
    HUGGINGFACE_IMPORT_ERROR = exc

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception as exc:
    RecursiveCharacterTextSplitter = None
    TEXT_SPLITTER_IMPORT_ERROR = exc

try:
    from langchain_core.prompts import ChatPromptTemplate
except Exception as exc:
    ChatPromptTemplate = None
    CHAT_PROMPT_IMPORT_ERROR = exc

try:
    from langchain_community.document_loaders import PyPDFDirectoryLoader
except Exception as exc:
    PyPDFDirectoryLoader = None
    PDF_LOADER_IMPORT_ERROR = exc

try:
    from langchain_community.vectorstores import FAISS
except Exception as exc:
    FAISS = None
    FAISS_IMPORT_ERROR = exc

project_dir = os.path.dirname(os.path.abspath(__file__))
for dotenv_path in [
    os.path.join(project_dir, ".env"),
    os.path.join(project_dir, "env.txt"),
]:
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path=dotenv_path, override=True)

openai_api_key = os.getenv("OPENAI_API_KEY") or ""
groq_api_key = os.getenv("GROQ_API_KEY") or ""
use_openai_embeddings = os.getenv("USE_OPENAI_EMBEDDINGS", "false").strip().lower() in {"1", "true", "yes", "on"}

if openai_api_key:
    os.environ["OPENAI_API_KEY"] = openai_api_key
if groq_api_key:
    os.environ["GROQ_API_KEY"] = groq_api_key

if not groq_api_key:
    st.set_page_config(page_title="RAG Document Q&A", page_icon="📄")

if groq_api_key and ChatGroq is not None:
    llm = ChatGroq(groq_api_key=groq_api_key, model_name="llama-3.1-8b-instant")
else:
    llm = None

if ChatPromptTemplate is not None:
    prompt = ChatPromptTemplate.from_template(
        """
        Answer the questions based on the provided context only.
        Please provide the most accurate response based on the question.
        <context>
        {context}
        <context>
        Question:{input}

        """
    )
else:
    prompt = None

def create_vector_embedding():
    if OpenAIEmbeddings is None or PyPDFDirectoryLoader is None or RecursiveCharacterTextSplitter is None or FAISS is None:
        st.error("One or more required LangChain dependencies failed to import. Please reinstall the affected packages and restart the app.")
        st.stop()

    if "vectors" not in st.session_state:
        embedding_model = None
        embedding_label = None

        if openai_api_key and use_openai_embeddings and OpenAIEmbeddings is not None:
            try:
                embedding_model = OpenAIEmbeddings(api_key=openai_api_key, model="text-embedding-3-small")
                embedding_label = "OpenAI"
            except Exception as exc:
                st.warning(f"OpenAI embedding setup failed: {exc}. Trying the local fallback.")

        if embedding_model is None and HuggingFaceEmbeddings is not None:
            embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
            embedding_label = "Hugging Face"

        if embedding_model is None:
            st.error("No embedding provider is available. Add OPENAI_API_KEY or install langchain-huggingface.")
            st.stop()

        st.session_state.embeddings = embedding_model
        st.session_state.loader = PyPDFDirectoryLoader("research_papers")
        st.session_state.docs = st.session_state.loader.load()

        if not st.session_state.docs:
            st.error("No PDF documents were found in the 'research_papers' folder.")
            st.stop()

        st.session_state.text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        st.session_state.final_documents = st.session_state.text_splitter.split_documents(st.session_state.docs[:50])

        if not st.session_state.final_documents:
            st.error("The PDF files were loaded, but no text could be extracted into chunks.")
            st.stop()

        try:
            st.session_state.vectors = FAISS.from_documents(st.session_state.final_documents, st.session_state.embeddings)
            st.success(f"Vector database created using {embedding_label} embeddings.")
        except KeyboardInterrupt:
            st.error("Embedding creation was interrupted. Please try again.")
            st.stop()
        except Exception as exc:
            error_text = str(exc).lower()
            if embedding_label == "OpenAI" and HuggingFaceEmbeddings is not None and (
                "quota" in error_text or "429" in error_text or "insufficient_quota" in error_text
            ):
                st.warning("OpenAI quota was exhausted. Retrying with local Hugging Face embeddings.")
                fallback_embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
                try:
                    st.session_state.embeddings = fallback_embeddings
                    st.session_state.vectors = FAISS.from_documents(st.session_state.final_documents, fallback_embeddings)
                    st.success("Vector database created using Hugging Face embeddings after OpenAI quota fallback.")
                except Exception as fallback_exc:
                    st.error(f"Vector embedding failed: {fallback_exc}")
                    st.stop()
            else:
                st.error(f"Vector embedding failed: {exc}")
                st.stop()


st.title("RAG Document Q&A With Groq And Llama3")

user_prompt = st.text_input("Enter your query from the research paper")

if st.button("Document Embedding"):
    create_vector_embedding()
    st.write("Vector Database is ready")

if user_prompt:
    if not groq_api_key:
        st.error("GROQ_API_KEY is missing. Add it to your .env file or environment variables.")
        st.stop()

    if llm is None or prompt is None:
        st.error("The LLM stack could not be initialized. Please fix the dependency import issue and restart the app.")
        st.stop()

    if "vectors" not in st.session_state:
        st.warning("Please build the vector database first by clicking 'Document Embedding'.")
        st.stop()

    retriever = st.session_state.vectors.as_retriever()
    start = time.process_time()
    try:
        relevant_docs = retriever.get_relevant_documents(user_prompt)
    except AttributeError:
        relevant_docs = retriever.invoke(user_prompt)
    context = "\n\n".join(doc.page_content for doc in relevant_docs)

    formatted_messages = prompt.format_messages(context=context, input=user_prompt)
    response = llm.invoke(formatted_messages)
    answer = response.content if hasattr(response, "content") else str(response)
    print(f"Response time :{time.process_time()-start}")

    st.write(answer)

    with st.expander("Document similarity Search"):
        for doc in relevant_docs:
            st.write(doc.page_content)
            st.write('------------------------')






