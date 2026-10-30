# Vestuário diário e boletins a cada duas horas

## O que foi preparado

Dez vídeos derivados do clipe original, com a mesma blusa em dez cores:
branco, azul-marinho, azul-petróleo, verde-esmeralda, bordô, ameixa, grafite,
azul executivo, terracota e verde-oliva. Não são dez cortes novos de roupa.
O processo preserva a identidade e os movimentos do vídeo-base; pode haver
pequenas imperfeições de máscara nos contornos da roupa.

Veja `templates/vestuario/previa-vestuario.jpg` e `catalogo.json`. Os MP4s
são silenciosos: a voz e a música continuam vindo da montagem do boletim.
Não houve contratação de um gerador pago de vídeo.

## Seleção diária

`app/wardrobe.py` escolhe a cor pela data no fuso `America/Belem`. A escolha
é determinística, percorre dez cores antes de repetir e não muda entre os
boletins do mesmo dia. A âncora do ciclo fica no catálogo; mudar sua ordem
altera a sequência dos dias seguintes.

O job registra a escolha, a data e o hash em `vestuario.json`. Se for retomado
após meia-noite, conserva a roupa que já havia escolhido. A API passa a data
de criação do job, garantindo uma referência consistente mesmo com fila.
Uma alteração inesperada do arquivo de roupa é detectada pelo hash.

`production.py` e a renderização oficial manual usam a seleção diária antes
da sincronização labial. Não é necessário editar as cores a cada vídeo, nem
executar segmentação durante a geração de cada boletim.
`PRESENTER_WARDROBE_CATALOG` permite indicar outro catálogo preparado.

## Agendamento

Configuração no `render.yaml`:

```text
VIDEO_INTERVAL_HOURS=2
VIDEO_TIMEZONE=America/Belem
```

São doze horários locais por dia: 00h, 02h, 04h, 06h, 08h, 10h, 12h, 14h,
16h, 18h, 20h e 22h. Ao iniciar o serviço, ele cria ou recupera o job do
intervalo atual, sem gerar todos os horários passados. Se o processamento
atrasar, os jobs seguintes permanecem na fila; não se promete publicação exata
na hora marcada. Esse agendamento substitui o diário quando está configurado.

`jobs.sqlite3`, dentro de `VIDEO_OUTPUT_DIR`, guarda jobs e chaves únicas dos
intervalos. A fila retoma jobs interrompidos e evita novo disparo do mesmo
intervalo após reinicialização. Esta implementação é para **uma instância do
worker**. Para escalar, usar uma fila distribuída e uma única liderança de agenda.

O serviço precisa estar rodando para agendar. Em produção, `VIDEO_OUTPUT_DIR`
precisa estar em armazenamento persistente: `/tmp` não garante histórico após
recriar o servidor. Configurar arquivos localmente não implanta nem mantém o
servidor online. Não foi configurada publicação automática no YouTube.

## Preparar novamente as cores

O script de preparação usa OpenCV e ONNX Runtime no ambiente local e requer
`.local/u2netp.onnx` (modelo de segmentação U²-NetP do projeto rembg).
Dependências de preparação não são necessárias no servidor, pois os dez clipes
já estão prontos dentro de `templates/vestuario`, copiados pelo Docker.

```bash
.local/venv/bin/python \
  scripts/build_wardrobe.py
```

O script foi ajustado para a blusa branca do clipe aprovado. Trocar por outro
clipe ou corte exige verificar a segmentação antes de usar em produção.
O download do modelo utilizado foi:
`https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx`.

O modelo labial permanece necessário no worker, com as limitações e licença
já documentadas no template oficial. O vestuário diário não resolve essa etapa
nem reduz o custo de sincronizar novas falas.
