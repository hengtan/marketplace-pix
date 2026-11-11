import argparse
import asyncio
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from assistant.application.evaluation import EvalCase, load_cases, percentile
from assistant.application.ingest import IngestCatalog
from assistant.application.rerank import LexicalReranker
from assistant.application.retrieval import HybridRetriever, RetrievalConfig
from assistant.config import load_settings
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.metrics import (
    context_precision,
    context_recall,
    hit_at_k,
    ndcg_at_k,
    reciprocal_rank,
)
from assistant.domain.understanding import Intent
from assistant.infrastructure.db.chunk_store import PgChunkStore
from assistant.infrastructure.db.session import build_engine, build_session_factory
from assistant.infrastructure.embedders.hashing import HashingEmbedder
from assistant.infrastructure.fixtures import SnapshotCatalogGateway
from assistant.wiring import retrieval_config

EVAL_DB = "assistant_rageval"
START, END = "<!-- rageval:start -->", "<!-- rageval:end -->"


@dataclass(frozen=True)
class Variant:
    name: str
    config: RetrievalConfig
    chunk: tuple[int, int] = (300, 60)
    intent_routing: bool = False
    note: str = ""


def variants(production: RetrievalConfig) -> list[Variant]:
    base = RetrievalConfig()
    return [
        Variant("baseline (hybrid + RRF + reranker)", base),
        Variant("pós-filtro em vez de pré-filtro", replace(base, prefilter=False)),
        Variant("pré-filtro, ramos de 5 candidatos", replace(base, branch_limit=5)),
        Variant(
            "pós-filtro, ramos de 5 candidatos", replace(base, branch_limit=5, prefilter=False)
        ),
        Variant(
            "pesos RRF 0.5 vetor / 1.5 texto", replace(base, vector_weight=0.5, text_weight=1.5)
        ),
        Variant(
            "pesos RRF 1.5 vetor / 0.5 texto", replace(base, vector_weight=1.5, text_weight=0.5)
        ),
        Variant("+ correção de digitação", replace(base, typo_correction=True)),
        Variant("+ expansão de sinônimos (sempre)", replace(base, rewrite="always")),
        Variant("+ expansão de sinônimos (adaptativa)", replace(base, rewrite="adaptive")),
        Variant("+ HyDE (documento hipotético)", replace(base, hyde=True)),
        Variant("+ negação", replace(base, negation=True)),
        Variant("+ decomposição", replace(base, decompose=True)),
        Variant("+ MMR lambda 0.7", replace(base, mmr=True, mmr_lambda=0.7)),
        Variant("+ MMR lambda 0.4", replace(base, mmr=True, mmr_lambda=0.4)),
        Variant("+ roteamento de intenção", base, intent_routing=True),
        Variant("chunks pequenos (150/30)", base, chunk=(150, 30)),
        Variant("parent-document (chunks 300/60)", replace(base, parent_documents=True)),
        Variant(
            "chunks pequenos + parent-document", replace(base, parent_documents=True), (150, 30)
        ),
        Variant(
            "combo: adaptativa + digitação + negação + decomposição",
            replace(production, rewrite="adaptive", hyde=False, mmr=False, parent_documents=False),
            intent_routing=True,
        ),
        Variant(
            "combo: sempre + digitação + negação + decomposição",
            replace(production, rewrite="always", hyde=False, mmr=False, parent_documents=False),
            intent_routing=True,
        ),
        Variant(
            "combo anterior + HyDE",
            replace(production, rewrite="always", hyde=True, mmr=False, parent_documents=False),
            intent_routing=True,
        ),
        Variant(
            "combo anterior + MMR 0.7",
            replace(
                production,
                rewrite="always",
                hyde=False,
                mmr=True,
                mmr_lambda=0.7,
                parent_documents=False,
            ),
            intent_routing=True,
        ),
        Variant("produção (configuração padrão do serviço)", production, intent_routing=True),
    ]


@dataclass
class VariantResult:
    variant: Variant
    metrics: dict[str, float] = field(default_factory=dict)
    by_split: dict[str, dict[str, float]] = field(default_factory=dict)
    by_category: dict[str, float] = field(default_factory=dict)


def retrieval_cases(cases: list[EvalCase]) -> list[EvalCase]:
    return [
        c
        for c in cases
        if not c.history
        and c.expected_tool in (None, "search_products", "none")
        and (c.expected_products or c.forbidden_products or _abstains(c))
    ]


def _abstains(case: EvalCase) -> bool:
    return not case.expected_products and (
        case.expected_tool == "none" or any("Não encontrei" in s for s in case.must_include)
    )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


async def evaluate(
    retriever: HybridRetriever, cases: list[EvalCase], routing: bool
) -> tuple[dict[str, float], dict[str, dict[str, float]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    latencies: list[int] = []
    for case in cases:
        started = time.perf_counter()
        slugs: list[str] = []
        result = None
        routed_out = False
        if routing:
            routed_out = (
                await retriever.understanding.classify(case.question)
            ).intent == Intent.OUT_OF_SCOPE
        if not routed_out:
            result = await retriever.retrieve(case.question)
            slugs = [p.slug for p in result.passages]
        latencies.append(int((time.perf_counter() - started) * 1000))
        row: dict[str, Any] = {"case": case, "slugs": slugs}
        if result is not None and result.passages:
            row["price_ctx"] = _mean(["Preço:" in p.content for p in result.passages])
        expected = set(case.expected_products)
        if expected:
            row["hit1"] = float(hit_at_k(slugs, expected, 1, case.require_all))
            row["hit3"] = float(hit_at_k(slugs, expected, 3, case.require_all))
            row["rr"] = reciprocal_rank(slugs, expected)
            row["ndcg"] = ndcg_at_k(slugs, dict.fromkeys(expected, 1.0), 5)
            row["cp"] = context_precision(slugs, expected)
            row["cr"] = context_recall(slugs, expected, 4)
        if case.forbidden_products:
            row["neg"] = float(not set(case.forbidden_products) & set(slugs))
        if _abstains(case):
            row["abst"] = float(not slugs)
        rows.append(row)

    def mean(key: str, subset: list[dict[str, Any]] | None = None) -> float:
        return _mean([r[key] for r in (subset if subset is not None else rows) if key in r])

    metrics = {
        "hit@1": mean("hit1"),
        "hit@3": mean("hit3"),
        "mrr": mean("rr"),
        "ndcg@5": mean("ndcg"),
        "ctx_prec": mean("cp"),
        "ctx_rec": mean("cr"),
        "negação": mean("neg"),
        "abstenção": mean("abst"),
        "ctx_preço": mean("price_ctx"),
        "p50_ms": float(percentile(latencies, 50)),
    }
    by_split = {}
    for split in ("dev", "holdout"):
        subset = [r for r in rows if r["case"].split == split]
        by_split[split] = {"hit@3": mean("hit3", subset), "mrr": mean("rr", subset)}
    categories = sorted({r["case"].category for r in rows})
    by_category = {}
    for cat in categories:
        subset = [r for r in rows if r["case"].category == cat]
        if any("hit3" in r for r in subset):
            by_category[cat] = mean("hit3", subset)
    return metrics, by_split, by_category


async def ensure_database(name: str) -> None:
    settings = load_settings()
    admin = create_async_engine(
        settings.database_url.replace(f"/{settings.assistant_db}", "/postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": name}
        )
        if not exists:
            await conn.execute(text(f'create database "{name}"'))
    await admin.dispose()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "ASSISTANT_DB": name},
        check=True,
        capture_output=True,
    )


async def run_all(fixture: Path, cases_path: Path) -> list[VariantResult]:
    await ensure_database(EVAL_DB)
    os.environ["ASSISTANT_DB"] = EVAL_DB
    settings = load_settings()
    if not settings.assistant_db.endswith("_rageval"):
        raise SystemExit("refusing to truncate a database that is not *_rageval")
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    store = PgChunkStore(factory)
    embedder = HashingEmbedder(settings.embedding_dim)
    catalog = SnapshotCatalogGateway(fixture)
    cases = retrieval_cases(load_cases(cases_path))
    plan = variants(retrieval_config(settings))
    results: list[VariantResult] = []
    try:
        for chunk in sorted({v.chunk for v in plan}, reverse=True):
            async with engine.begin() as conn:
                await conn.execute(text("truncate chunks"))
            await IngestCatalog(catalog, store, embedder, RecursiveChunker(*chunk)).execute()
            for variant in (v for v in plan if v.chunk == chunk):
                retriever = HybridRetriever(store, embedder, LexicalReranker(), variant.config)
                metrics, by_split, by_category = await evaluate(
                    retriever, cases, variant.intent_routing
                )
                results.append(VariantResult(variant, metrics, by_split, by_category))
    finally:
        await engine.dispose()
    order = {v.name: i for i, v in enumerate(plan)}
    results.sort(key=lambda r: order[r.variant.name])
    results.append(VariantResult(Variant("_cases", RetrievalConfig()), {"n": float(len(cases))}))
    return results


def render(results: list[VariantResult]) -> str:
    total = int(results[-1].metrics["n"])
    results = results[:-1]
    head = (
        "| variante | hit@1 | hit@3 | MRR | nDCG@5 | prec. ctx | rev. ctx | negação | "
        "abstenção | ctx com preço | hit@3 dev | hit@3 holdout | MRR holdout | p50 ms |"
    )
    lines = [f"Casos de recuperação avaliados: {total}.", "", head, "|" + "---|" * 14]
    baseline = results[0].metrics
    for r in results:
        m = r.metrics
        cells = [
            r.variant.name,
            _cell(m["hit@1"], baseline["hit@1"]),
            _cell(m["hit@3"], baseline["hit@3"]),
            _cell(m["mrr"], baseline["mrr"]),
            _cell(m["ndcg@5"], baseline["ndcg@5"]),
            _cell(m["ctx_prec"], baseline["ctx_prec"]),
            _cell(m["ctx_rec"], baseline["ctx_rec"]),
            _cell(m["negação"], baseline["negação"]),
            _cell(m["abstenção"], baseline["abstenção"]),
            _cell(m["ctx_preço"], baseline["ctx_preço"]),
            f"{r.by_split['dev']['hit@3']:.3f}",
            f"{r.by_split['holdout']['hit@3']:.3f}",
            f"{r.by_split['holdout']['mrr']:.3f}",
            f"{m['p50_ms']:.0f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    first, last = results[0], results[-1]
    lines += ["", "hit@3 por categoria, baseline contra produção:", ""]
    lines.append("| categoria | baseline | produção |")
    lines.append("|---|---|---|")
    for cat, value in first.by_category.items():
        lines.append(f"| {cat} | {value:.3f} | {last.by_category.get(cat, 0.0):.3f} |")
    return re.sub(r"(?<=\d)\.(?=\d)", ",", "\n".join(lines))


def _cell(value: float, base: float) -> str:
    if abs(value - base) < 0.0005:
        return f"{value:.3f}"
    sign = "+" if value > base else ""
    return f"{value:.3f} ({sign}{value - base:.3f})"


def write_docs(path: Path, table: str) -> None:
    content = path.read_text(encoding="utf-8")
    start, end = content.index(START) + len(START), content.index(END)
    path.write_text(content[:start] + "\n" + table + "\n" + content[end:], encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m assistant.rageval")
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/catalog.json"))
    parser.add_argument("--cases", type=Path, default=Path("evals/cases.yaml"))
    parser.add_argument("--write-docs", type=Path, default=None)
    args = parser.parse_args()
    table = render(asyncio.run(run_all(args.fixture, args.cases)))
    print(table)
    if args.write_docs:
        write_docs(args.write_docs, table)


if __name__ == "__main__":
    main()
