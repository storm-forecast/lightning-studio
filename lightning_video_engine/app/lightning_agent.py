"""Strict client for Lightning Agent data and its authorised visual page."""

import json
import time
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ALLOWED_PRODUCTS = {
    "deterministico_ecens": "/previsao/mapa/deterministico.png?fonte=ecens&agregacao=dia",
    "probabilidade_ecens": "/previsao/mapa/probabilidade.png?fonte=ecens&agregacao=dia",
}


class LightningAgentClient:
    def __init__(self, base_url: str, app_url: str):
        self.base_url = base_url.rstrip("/")
        self.app_url = app_url
        # Public editorial endpoints rate-limit bursts. CI runs use a small
        # interval so a long bulletin finishes instead of losing its last scenes.
        self.min_interval = max(0.0, float(os.environ.get('VIDEO_AGENT_MIN_INTERVAL', '0')))
        self._last_request_at = 0.0

    def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def mapa(self, product: str) -> bytes:
        """Download exactly one allowlisted product from lightning-agent."""
        try:
            path = ALLOWED_PRODUCTS[product]
        except KeyError as exc:
            raise ValueError("produto não autorizado") from exc
        with urlopen(self.base_url + path, timeout=60) as response:
            return response.read()

    def destaques_editoriais(self, top_n: int = 20) -> dict:
        """Read deterministic ECENS highlights calculated by the data API."""
        query = urlencode({"top_n": max(3, min(int(top_n), 50))})
        with urlopen(self.base_url + "/previsao/destaques-editoriais?" + query, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("fonte") != "ecens":
            raise RuntimeError("destaques editoriais sem confirmação ECENS")
        return result

    def referencias_alagamento(self, areas: list) -> dict:
        """Resolve actual captured polygon geometry, never infer city names in the LLM."""
        from .tourism import tourism_targets
        request = Request(self.base_url + '/previsao/referencias-alagamento',
            data=json.dumps({'areas': areas, 'locais_interesse': tourism_targets()}, allow_nan=False).encode(),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
        with urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode('utf-8'))
        if result.get('tipo') != 'associacao_geografica' or not isinstance(result.get('areas'), list):
            raise RuntimeError('associação geográfica de alagamento inválida')
        # Only IDs of captured areas may be used in the narration.
        valid_ids = {area['id'] for area in areas}
        if any(row.get('id') not in valid_ids for row in result['areas']):
            raise RuntimeError('associação geográfica não corresponde à captura')
        if any(not set(row.get('areas_ids', [])) <= valid_ids or row.get('dentro_poligono') is not True for row in result.get('locais_interesse', [])):
            raise RuntimeError('destino turístico sem associação à área capturada')
        return result

    def resumo_observado(self) -> dict:
        """Structured observed hotspots, not a language-model summary."""
        with urlopen(self.base_url + '/observado/resumo?top_n=50', timeout=180) as response:
            result = json.loads(response.read().decode('utf-8'))
        if not isinstance(result.get('regioes'), list) or not result.get('inicio') or not result.get('fim'):
            raise RuntimeError('resumo observado sem localidades e janela temporal válidas')
        return result

    def captura_app(self, destination: Path) -> None:
        """Capture the official /app/ visual with Chromium; no third-party map page is used."""
        browser = os.environ.get("CHROMIUM_BIN", "chromium")
        binary = browser if Path(browser).exists() else shutil.which(browser)
        if not binary:
            raise RuntimeError("Chromium não configurado no worker")
        subprocess.run([binary, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--window-size=1920,1080", "--virtual-time-budget=10000",
                        f"--screenshot={destination}", self.app_url], check=True, timeout=45)

    def narrar(self, instrucoes: str, evidencias: dict) -> dict:
        """Use the one-pass narrator; old deployments retain the existing chat path."""
        if getattr(self, '_bulletin_supported', True):
            request = Request(self.base_url + '/chat/boletim',
                data=json.dumps({'instrucoes': instrucoes, 'evidencias': evidencias}, ensure_ascii=False).encode(),
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
            try:
                self._pace()
                with urlopen(request, timeout=60) as response:
                    result = json.loads(response.read().decode('utf-8'))
                if not isinstance(result.get('resposta'), str) or not result['resposta'].strip():
                    raise RuntimeError('narrador devolveu uma fala vazia')
                return result
            except HTTPError as exc:
                if exc.code not in (404, 405):
                    raise RuntimeError(f'narrador indisponível (HTTP {exc.code})') from exc
                self._bulletin_supported = False
            except (URLError, TimeoutError, ValueError) as exc:
                raise RuntimeError('narrador não respondeu com evidências válidas') from exc
        return self.perguntar(instrucoes + '\nEvidências estruturadas: ' + json.dumps(evidencias, ensure_ascii=False))

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
            self._pace()
            with urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
            answer = str(result.get('resposta', ''))
            technical = ('muitas perguntas', 'groq não respondeu', 'tente de novo',
                         'agente está indisponível', 'erro ao consultar')
            if not any(message in answer.lower() for message in technical):
                break
            if attempt == 2:
                raise RuntimeError('agente sem resposta editorial válida após três tentativas')
            # The response is a service-rate limit, not editorial evidence.
            # Increase the delay on each retry instead of narrating it.
            time.sleep(30 * (attempt + 1))

        answer = result.get("resposta")
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("o agente não devolveu uma resposta utilizável")
        return result
