# Migração do código

Origem: `/home/gabriel/Área de trabalho/lightning-Agent/lightning-video-engine`.
Destino: `/home/gabriel/Área de trabalho/lightning-studio`.

Código, scripts, testes, prompts, documentação, configurações e templates da
API foram copiados para o novo repositório, preservando seu `.git` e README
anterior. Os 8 GB de modelos/ambientes e os vídeos históricos continuam na origem.
Os templates originais também foram preservados para manter as referências dos
vídeos arquivados. Docker e Render agora usam a raiz do Lightning Studio.

`LIPSYNC_PYTHON` e `WAV2LIP_ROOT` permitem usar modelos locais armazenados fora
deste repositório, sem copiar ambientes virtuais ou pesos. Para independência
completa de execução, provisione esses recursos no novo servidor.

Após a validação, foram retirados da origem apenas `lightning_video_engine/`,
`scripts/`, `tests/`, `Dockerfile`, `render.yaml` e `requirements.txt`, todos
preservados no destino. Modelos, ambientes, vídeos e recursos históricos não
foram movidos nem excluídos. Os 16 testes passaram no novo repositório.
