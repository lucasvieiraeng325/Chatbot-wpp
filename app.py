from fastapi import FastAPI

app = FastAPI(title="Chatbot WhatsApp IA")


@app.get("/")
def home():
    return {
        "status": "online",
        "mensagem": "Chatbot funcionando!"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }
