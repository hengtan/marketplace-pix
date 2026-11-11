from pydantic import BaseModel, Field

from assistant.application.judge import JudgeInput, JudgeVerdict
from assistant.application.ports import LlmClient, Prompt
from assistant.application.structured import generate_structured

JUDGE_SYSTEM = (
    "Você é um avaliador rigoroso de respostas de um assistente de compras. Dê notas de 0 a 1 "
    "e responda somente com JSON no formato "
    '{"faithfulness": 0.0, "relevancy": 0.0, "reasons": ["..."]}. '
    "faithfulness: toda afirmação da resposta está sustentada pelo contexto? "
    "relevancy: a resposta atende à pergunta? Recusar é correto quando o contexto não cobre a "
    "pergunta."
)


class JudgeScores(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0)
    relevancy: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class LlmJudge:
    """Judge backed by a language model. The reply is validated with pydantic and repaired
    through `generate_structured`, so a malformed score never reaches the metrics."""

    def __init__(self, llm: LlmClient, max_retries: int = 2) -> None:
        self._llm = llm
        self._retries = max_retries

    async def judge(self, item: JudgeInput) -> JudgeVerdict:
        context = "\n".join(f"[{i}] {text}" for i, text in enumerate(item.contexts, start=1))
        evidence = "\n".join(item.evidence)
        text = (
            f"{JUDGE_SYSTEM}\n\nPergunta: {item.question}\n\nContexto:\n{context}\n\n"
            f"Observações de ferramentas:\n{evidence}\n\nResposta avaliada:\n{item.answer}\n\n"
            f"A pergunta {'tem' if item.answerable else 'não tem'} resposta no catálogo."
        )
        prompt = Prompt(JUDGE_SYSTEM, item.question, (), (), text)
        scores = await generate_structured(self._llm, prompt, JudgeScores, self._retries)
        return JudgeVerdict(scores.faithfulness, scores.relevancy, tuple(scores.reasons))
