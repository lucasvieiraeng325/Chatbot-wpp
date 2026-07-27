from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import os

app = FastAPI(title="Chatbot WhatsApp IA")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class Pergunta(BaseModel):
    mensagem: str


@app.get("/")
def home():
    return {
        "status": "online",
        "mensagem": "Chatbot funcionando!"
    }


@app.post("/chat")
def chat(pergunta: Pergunta):

    resposta = client.responses.create(
        model="gpt-5.5",
        input=pergunta.mensagem
    )

    return {
        "resposta": resposta.output_text
    }
