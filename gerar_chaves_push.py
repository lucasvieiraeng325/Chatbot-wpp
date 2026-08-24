"""
Gera o par de chaves VAPID para as notificações push.
Rode uma vez e guarde os valores nas variáveis de ambiente do Render.

    python gerar_chaves_push.py
"""
import base64
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization

v = Vapid01()
v.generate_keys()

privada = base64.urlsafe_b64encode(
    v.private_key.private_numbers().private_value.to_bytes(32, "big")
).decode().rstrip("=")

publica = base64.urlsafe_b64encode(
    v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
).decode().rstrip("=")

print("Adicione no Render (Environment):\n")
print(f"VAPID_PUBLICA={publica}")
print(f"VAPID_PRIVADA={privada}")
print("\nGuarde as duas. Se perder a privada, todos os aparelhos")
print("precisarão ativar as notificações de novo.")
