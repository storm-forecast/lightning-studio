# Instalação automática no deploy

O Docker instala dependências de CPU, FFmpeg, Chromium e código Wav2Lip fixado.
Na inicialização, baixa o checkpoint por `WAV2LIP_CHECKPOINT_URL`, verifica SHA-256
e só então inicia a API e sua agenda. Aceita arquivo `.pth` ou ZIP com um único
`wav2lip-compatible.pth`. O modelo não vai para o GitHub nem é incluído na imagem.

1. Envie `deploy-assets/lightning-studio-model.zip` ao Drive ou a outro
   armazenamento que o servidor consiga acessar.
2. Configure `WAV2LIP_CHECKPOINT_URL` com o link de download. O link precisa
   permitir download sem sessão de navegador; pode ser assinado/temporário.
3. Faça deploy pelo Docker/Render. Não é necessário instalar pacotes manualmente.

O token da API é gerado pelo Blueprint Render. A porta usa `PORT`. Usa-se um
único worker para a agenda/fila SQLite. Persista `/data` para manter o modelo,
a fila e os vídeos entre deploys. Sem volume persistente, o download se repete
e o histórico local é perdido quando o container for recriado.

Nenhum plano pago ou disco foi contratado. Escolha um servidor com memória
suficiente para PyTorch e o modelo; o Render gratuito não garante execução
contínua da agenda e não oferece disco persistente. Código preparado para deploy
não equivale a servidor já publicado.

A voz e os dados meteorológicos ainda dependem de internet. O Wav2Lip mantém
as restrições comerciais de sua licença; este instalador não as altera.

## Preparação local

```bash
bash scripts/install_local.sh --checkpoint-file /caminho/do/pacote.zip
.local/venv/bin/python scripts/bootstrap_runtime.py --check-only
.local/venv/bin/python -m uvicorn lightning_video_engine.app.main:app --port 8100
```

O `.env` é carregado automaticamente pelo pacote. Variáveis do servidor prevalecem
sobre ele. Ativar `VIDEO_INTERVAL_HOURS=2` cria o job do intervalo atual ao iniciar.

No uso local fora do Docker, FFmpeg e Chromium precisam estar instalados no
sistema. Dentro do Docker, são instalados automaticamente durante o build.

Validação: 19 testes, renderização curta, download HTTP do ZIP e saúde da API
passaram com o ambiente próprio. A imagem Docker não foi construída neste
ambiente porque o executável Docker não está disponível. Ver `validation.json`.
