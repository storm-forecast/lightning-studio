# Lightning Studio API

API for generating weather video bulletins with synchronized maps, narration,
and a virtual presenter, using ECENS forecasts and AI models.

## Deploy automático

O Docker instala bibliotecas Python, PyTorch de CPU, FFmpeg, Chromium e o código
Wav2Lip na revisão validada. Na inicialização, baixa e verifica o modelo e inicia
a API com um único worker. A porta usa a variável `PORT` do provedor.

### Configuração inicial do modelo

1. Envie `deploy-assets/lightning-studio-model.zip` (aproximadamente 129 MiB)
   para o Drive ou outro armazenamento acessível ao servidor.
2. O link do Drive fornecido já está configurado em `WAV2LIP_CHECKPOINT_URL` no Blueprint; mantenha o arquivo acessível para download.
3. Faça deploy usando o `Dockerfile` ou o Blueprint `render.yaml`.

O link deve permitir download sem login interativo. Pode ser um link compartilhado
do Drive ou uma URL direta/assinada. O arquivo é verificado pelo SHA-256 em
`deploy/model.json`. Não coloque o modelo, ZIP, ambiente virtual ou `.env` no Git.

No Render, `VIDEO_ENGINE_TOKEN` é gerado pelo Blueprint. Criar/consultar jobs
exige `X-Video-Token`; a documentação fica em `/docs` e a saúde em `/health`.
O Render Free mantém somente a API: `VIDEO_AUTOSTART=false` evita renderização
automática em uma instância de 512 MB. A geração remota é feita pelo workflow
GitHub Actions em `.github/workflows/generate-video.yml`. A roupa troca uma vez
por dia, entre dez cores do mesmo corte profissional.

Persista `/data` para manter modelo, fila SQLite e vídeos entre deploys.
Use uma única instância do worker e capacidade de memória suficiente para
PyTorch. Nenhum serviço pago foi contratado. O plano gratuito do Render não
oferece disco persistente e pode suspender a aplicação inativa: ele não garante
esse agendamento contínuo. Consulte [os limites do provedor](https://render.com/docs/free).

[Detalhes da instalação automática](deploy/README.md).

## Ambiente local

O ambiente próprio em `.local/venv` foi criado e validado com PyTorch de CPU.
O código e o checkpoint labial também ficam em `.local/Wav2Lip`; a execução
não depende mais da pasta antiga do Lightning Agent.

Para preparar uma máquina nova:

```bash
bash scripts/install_local.sh --checkpoint-file /caminho/lightning-studio-model.zip
```

Para iniciar:

```bash
bash scripts/start.sh
```

O `.env` é carregado automaticamente. Variáveis já definidas pelo servidor
prevalecem sobre ele. `.env.example` contém as opções sem segredos.
`VIDEO_AUTOSTART=true` e `VIDEO_INTERVAL_HOURS=2` habilitam a agenda apenas em
um worker com memória suficiente. `VIDEO_PROFILE=balanced` preserva todas as
cenas continentais de previsão e nowcasting, sem as duas consultas locais;
`lite` produz somente quatro cenas essenciais; `full` preserva a sequência
editorial completa.

## Geração e testes

```bash
.local/venv/bin/python scripts/produce_bulletin.py --directory output/novo-boletim
.local/venv/bin/python -m unittest discover -s tests -v
.local/venv/bin/python scripts/bootstrap_runtime.py --check-only
```

O Lightning Agent continua fornecendo os dados pela rede. Chuva usa ECENS;
raios e suas áreas de risco são gerados pela IA com parâmetros convectivos
do ECENS. Cada cena tem áudio e tempo medidos, com sincronização labial e música.

[Template](templates/apresentacao-base.md) · [Processo](docs/processo-producao.md) ·
[Vestuário e agenda](docs/vestuario-e-agendamento.md)

O código está em `lightning_video_engine/app/`, com scripts, prompts e testes
nas pastas correspondentes. `.local`, `output` e `deploy-assets` são ignorados
pelo Git e pelo contexto Docker. O modelo mantém a restrição comercial de
Wav2Lip. Publicação automática no YouTube: ver `docs/youtube.md`.
O deploy online depende de conectar este repositório ao provedor de hospedagem.

## Geração gratuita no GitHub Actions

O workflow remoto envia os boletins ao YouTube para publicação diária às
**05:30, 09:00, 12:00, 13:00, 14:00 e 15:00, no horário de Brasília**. Ele
começa a geração 75 minutos antes e publica um artefato
temporário por 1 dia na aba **Actions**. Em **Settings → Secrets and variables
→ Actions**, crie `WAV2LIP_CHECKPOINT_URL` com o link público do pacote do
modelo. Não envie o ZIP nem tokens ao Git. O agendamento é uma conveniência:
execute também manualmente em **Actions → Generate weather bulletin → Run workflow**
quando precisar de uma publicação imediata.

O upload agendado permanece privado até o horário definido e então é liberado
automaticamente pelo YouTube. Se o GitHub Actions atrasar a geração além do
horário, o boletim atualizado é enviado publicamente assim que ficar pronto.
Uma mudança no workflow também inicia uma geração imediata para validação.
O agendamento remoto substitui a antiga cadência de duas horas e mantém a
execução manual disponível.
