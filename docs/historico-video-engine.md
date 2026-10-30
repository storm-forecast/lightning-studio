# Padrão oficial de vídeo

A versão aprovada é `output/boletim-oficial.mp4`. O template e as instruções
atuais estão em [templates/apresentacao-base.md](templates/apresentacao-base.md).
O worker usa `app/official.py` para aplicar o ritmo original, voz feminina
brasileira, sincronização labial e música. O modelo labial precisa ser
provisionado no worker; o Docker básico não o inclui. As seções abaixo
registram também opções anteriores, como Piper e Wav2Lip com imagem parada.

# Lightning Video Engine

Serviço separado do Lightning Agent para transformar os produtos meteorológicos já autorizados em vídeo.

## Arquitetura

```text
lightning-agent (Render web)
  ├─ https://lightning-agent.onrender.com/app/  fonte visual oficial do vídeo
  ├─ /previsao/mapa/{camada}.png     mapas autorizados
  ├─ /previsao/mapa                  período, limites e versão
  ├─ /observado/mapa                 flashes observados, quando habilitado
  └─ /desempenho/janelas             métricas de verificação, quando habilitado
                         │
                         ▼
lightning-video-engine (Render worker + web API)
  ├─ POST /v1/videos                 cria job
  ├─ GET  /v1/videos/{id}            acompanha job
  ├─ scheduler                        agenda boletim diário
  ├─ queue                            isola renderização da API
  ├─ roteiro                          perguntas sequenciais ao agente de /app/
  ├─ diretor visual                   clica em satélite, radar, raios e inundações na /app/
  ├─ Piper TTS                        narração local
  ├─ FFmpeg                           mapa + áudio → MP4
  └─ R2/S3 compatível                 entrega do MP4 e poster
```

## Regra de dados

O worker aceita somente os produtos declarados em `ALLOWED_PRODUCTS`. Não recebe URL arbitrária e não busca
radar, mapas ou textos fora do Lightning Agent. Isso permite auditoria simples de origem por vídeo.

O roteiro também não é escrito por um modelo separado: o worker abre uma conversa pelo mesmo endpoint
`POST /chat` utilizado na página `/app/`. Em uma mesma sessão ele pergunta, nesta ordem: panorama de raios
observados na América do Sul, previsão ECENS regional, cidades brasileiras, satélite/radar/inundação e
recomendações. A narração contém as respostas devolvidas pelo agente. Se a fonte não tiver confirmação,
o agente deve dizer isso; o vídeo não completa a lacuna por conta própria.

O boletim profissional usa uma pauta regional: América do Sul, severidade no Brasil, potencial de
alagamento, previsão para Norte/Nordeste/Centro-Oeste/Sudeste/Sul e países sul-americanos em destaque.

| Produto | Endpoint permitido |
| --- | --- |
| determinístico ECENS | `/previsao/mapa/deterministico.png?fonte=ecens&agregacao=dia` |
| probabilidade ECENS | `/previsao/mapa/probabilidade.png?fonte=ecens&agregacao=dia` |
| raios observados | `/observado/mapa` |
| desempenho ECENS | `/desempenho/janelas?fonte=ecens&agregacao=dia` |

## Variáveis de ambiente

```text
LIGHTNING_API_URL=https://lightning-agent.onrender.com
LIGHTNING_APP_URL=https://lightning-agent.onrender.com/app/
VIDEO_VISUAL_MODE=app
VIDEO_ENGINE_TOKEN=<segredo para criar jobs>
VIDEO_OUTPUT_DIR=/tmp/video-output
PIPER_VOICE=/opt/piper/voices/pt_BR-jeff-medium.onnx
FFMPEG_BIN=ffmpeg
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=30
VIDEO_DAILY_HOUR_UTC=12
PRESENTER_VIDEO=/data/avatar-apresentadora.webm
```

O Docker baixa a voz gratuita pt-BR Jeff (medium) do catálogo Piper. `PIPER_VOICE` e `FFMPEG_BIN` são
verificados antes de o job iniciar. Caso não estejam configurados, o job falha com mensagem explícita;
ele nunca tenta usar voz, dados ou serviço não autorizado.
`VIDEO_DAILY_HOUR_UTC` é opcional; quando definido (0–23), agenda um boletim diário em UTC.
Por padrão, `VIDEO_VISUAL_MODE=app` captura a interface oficial em `/app/` com Chromium. Para renderizar
somente o PNG de um produto autorizado, use `VIDEO_VISUAL_MODE=mapa`.

No modo `app`, o vídeo não usa mais uma imagem parada: o Playwright abre a página oficial, mantém a
abertura na América do Sul e registra uma sequência de satélite IR, radar, raios observados e potencial
de inundação. As cenas posteriores aproximam o Brasil. "Potencial de inundação" é sempre apresentado
como potencial, nunca como uma confirmação de alagamento.

## Apresentadora animada

`PRESENTER_VIDEO` recebe um MP4/WebM de avatar com lip-sync e gestos já sincronizados à narração. O
renderizador o sobrepõe às cenas do mapa. A geração desse clipe deve ser feita por um provedor de avatar
ou modelo de vídeo autorizado; uma imagem PNG não é tratada como se falasse ou gesticulasse.

### Execução local gratuita

Use Wav2Lip localmente para sincronizar a apresentadora com a voz Piper:

```bash
cd lightning-video-engine
bash scripts/setup_local_wav2lip.sh
# salve o checkpoint oficial em .local/Wav2Lip/checkpoints/wav2lip_gan.pth
bash scripts/render_local_avatar.sh
```

Sem GPU NVIDIA, o Wav2Lip cai para CPU e pode levar vários minutos por vídeo. O fluxo continua gratuito;
somente a velocidade é menor.

## Execução local

```bash
uvicorn lightning_video_engine.app.main:app --reload --port 8100
curl -X POST http://localhost:8100/v1/videos \
  -H 'Content-Type: application/json' \
  -H 'X-Video-Token: <token>' \
  -d '{"produto":"deterministico_ecens","titulo":"Boletim ECENS"}'
```

## Render

Publique como **Background Worker** para a fila e, opcionalmente, como um Web Service para receber jobs.
Para produção com mais de uma instância, substitua a fila em memória por Redis/RQ ou Cloudflare Queues;
o contrato HTTP e o formato dos jobs permanecem iguais.

## Narração feminina brasileira (padrão atual)

`TTS_PROVIDER=edge` e `EDGE_TTS_VOICE=pt-BR-FranciscaNeural` usam o serviço
online do Edge por meio de `edge-tts`. A narração é feminina em pt-BR, sem
fallback automático para Jeff. Exige internet; não há garantia de disponibilidade
ou volume diário. As instruções sobre Piper acima se aplicam à opção local
`TTS_PROVIDER=piper`, não à configuração padrão atual.

## Velocidade da apresentação

`PRESENTER_SPEED=1.0` preserva o ritmo natural do clipe original.
`NARRATION_SPEED=0.90` deixa a narração 10% mais lenta na montagem,
preservando o timbre com o filtro atempo. O áudio gerado fica intacto;
a redução é aplicada uma única vez ao exportar o boletim.
Use `1.0` para manter a velocidade original de cada faixa.
O ajuste não sincroniza os lábios com o novo roteiro.

## Boletim dirigido pelo prompt

`app/production.py` integra o prompt em `prompts/boletim-meteorologico.md` à
captura das camadas e à montagem com áudio por cena. Execute
`scripts/produce_bulletin.py --directory output/novo-job` com o ambiente local.
O diretório guarda roteiro, capturas, evidências, áudios, tempos e vídeo final.
Ver [processo de produção](docs/processo-producao.md) para revisão e retomada.

## Fonte das previsões e atribuição da IA

Todas as previsões usam exclusivamente ECENS, inclusive chuva. Se a chuva ECENS
não estiver disponível, informar a ausência sem substituir por GFS. A previsão
de raios e suas áreas de risco são geradas pelo modelo de inteligência artificial
usando parâmetros convectivos do ECENS; não são uma saída direta de raios do
modelo meteorológico. Essa distinção aparece na fala de abertura e permanece
escrita nas cenas de previsão de raios, inclusive nos destaques locais.
`forecast_policy.py` rejeita fontes e roteiros antigos incompatíveis.

## Vestuário diário e agenda de duas horas

Há dez cores do clipe da apresentadora em `templates/vestuario`. O código
seleciona uma por dia de Belém e registra a escolha no job. O `render.yaml`
configura `VIDEO_INTERVAL_HOURS=2`. A agenda e a fila usam SQLite para evitar
repetição de slots e retomar jobs. Exige uma instância ativa e diretório de
saída persistente; não equivale a implantação ou publicação no YouTube.
Veja [operação](docs/vestuario-e-agendamento.md).
