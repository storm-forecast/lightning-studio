"""Strict client for Lightning Agent data and its authorised visual page."""

import json
import time
import os
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen


ALLOWED_PRODUCTS = {
    "deterministico_ecens": "/previsao/mapa/deterministico.png?fonte=ecens&agregacao=dia",
    "probabilidade_ecens": "/previsao/mapa/probabilidade.png?fonte=ecens&agregacao=dia",
}


class LightningAgentClient:
    def __init__(self, base_url: str, app_url: str):
        self.base_url = base_url.rstrip("/")
        self.app_url = app_url

    def mapa(self, product: str) -> bytes:
        """Download exactly one allowlisted product from lightning-agent."""
        try:
            path = ALLOWED_PRODUCTS[product]
        except KeyError as exc:
            raise ValueError("produto não autorizado") from exc
        with urlopen(self.base_url + path, timeout=60) as response:
            return response.read()

    def captura_app(self, destination: Path) -> None:
        """Capture the official /app/ visual with Chromium; no third-party map page is used."""
        browser = os.environ.get("CHROMIUM_BIN", "chromium")
        binary = browser if Path(browser).exists() else shutil.which(browser)
        if not binary:
            raise RuntimeError("Chromium não configurado no worker")
        subprocess.run([binary, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=1920,1080", "--virtual-time-budget=10000",
                        f"--screenshot={destination}", self.app_url], check=True, timeout=45)

    def perguntar(self, pergunta: str, session_id: str | None = None) -> dict:
        """Ask the same public agent used by /app/, retaining its conversation id.

        The video service does not scrape chat bubbles or generate meteorological claims itself.
        Each editorial segment is an answer returned by Lightning Agent's ``/chat`` endpoint.
        """
        payload = {"pergunta": pergunta, "fuso": "America/Sao_Paulo"}
        if session_id:
            payload["session_id"] = session_id
        request = Request(
            f"{self.base_url}/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        for attempt in range(3):
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = str(result.get('resposta', ''))
            technical = ('muitas perguntas', 'groq não respondeu', 'tente de novo',
                         'agente está indisponível', 'erro ao consultar')
            if not any(message in answer.lower() for message in technical):
                break
            if attempt == 2:
                raise RuntimeError('agente sem resposta editorial válida após três tentativas')
            time.sleep(20)

        answer = result.get("resposta")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("o agente não devolveu uma resposta utilizável")
        return result
