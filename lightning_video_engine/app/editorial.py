"""Regional, evidence-led editorial brief for South America lightning videos."""

REGIONAL_QUESTIONS = (
    "Em até duas frases, descreva onde há raios observados agora na América do Sul, por regiões e países. Não invente locais.",
    "Em até duas frases, diga onde há maior severidade agora no Brasil, agrupando Norte, Nordeste, Centro-Oeste, Sudeste e Sul. Se não houver confirmação, diga isso.",
    "Em até duas frases, diga onde existe potencial de alagamento agora no Brasil. Trate como potencial, não como inundação confirmada.",
    "Em até três frases, resuma a previsão de raios e chuva de hoje para Norte, Nordeste, Centro-Oeste, Sudeste e Sul do Brasil, e Argentina ou outros países sul-americanos quando os dados confirmarem.",
    "Em uma frase, dê uma recomendação geral de segurança para raios e chuva forte, sem criar alertas oficiais.",
)


def pauta_regional(client) -> str:
    """Ask the public Lightning Agent once per editorial subject in one conversation."""
    session_id = None
    answers = []
    for question in REGIONAL_QUESTIONS:
        result = client.perguntar(question, session_id)
        session_id = result.get("session_id") or session_id
        answers.append(result["resposta"].strip())
    return " ".join(answers)
