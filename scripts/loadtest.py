#!/usr/bin/env python3
"""Teste de carga do gateway (asyncio + httpx, sem dependências extras).

Uso:
  python3 scripts/loadtest.py --base http://localhost:8000 --duration 30 --concurrency 40
  python3 scripts/loadtest.py --rps 200 --duration 20 --json docs/loadtest-result.json

Cenário: mistura de leituras (catálogo, estoque) e criação de pedidos com Idempotency-Key.
Os pedidos consomem estoque, por isso o script repõe o estoque dos produtos de seed antes de começar.
Sai com código 1 se a taxa de erros (5xx + falhas de transporte) passar de --max-error-rate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

try:
    import httpx
except ImportError:
    sys.exit("instale o httpx: pip install httpx")

SEED_PRODUCTS = [
    "fone-bluetooth-nova",
    "caixa-som-pulse",
    "teclado-mecanico-forge",
    "mouse-glide-pro",
    "luminaria-arco-dourado",
    "garrafa-termica-aco-750",
    "corda-pular-speed",
    "kit-elasticos-forca",
]


def product_id(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"marketplace-pix:product:{slug}"))


@dataclass
class Sample:
    endpoint: str
    status: int
    seconds: float
    error: str | None = None


@dataclass
class Stats:
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample) -> None:
        self.samples.append(sample)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def build_request(rng: random.Random) -> tuple[str, str, str, dict[str, object]]:
    roll = rng.random()
    if roll < 0.40:
        page = rng.randint(1, 2)
        return "list_products", "GET", f"/api/catalog/products?page={page}&page_size=12", {}
    if roll < 0.60:
        slug = rng.choice(SEED_PRODUCTS)
        return "product_by_slug", "GET", f"/api/catalog/products/slug/{slug}", {}
    if roll < 0.70:
        return "categories", "GET", "/api/catalog/categories", {}
    if roll < 0.90:
        ids = ",".join(product_id(s) for s in rng.sample(SEED_PRODUCTS, 3))
        return "stock", "GET", f"/api/inventory/stock?product_ids={ids}", {}
    body = {
        "customer_id": str(uuid.uuid4()),
        "customer_name": "Carga",
        "customer_email": "carga@example.com",
        "items": [{"product_id": product_id(rng.choice(SEED_PRODUCTS)), "quantity": 1}],
    }
    return (
        "create_order",
        "POST",
        "/api/orders",
        {"json": body, "headers": {"Idempotency-Key": uuid.uuid4().hex}},
    )


async def worker(
    client: httpx.AsyncClient,
    stats: Stats,
    stop_at: float,
    interval: float,
    seed: int,
    timeout: float,
) -> None:
    rng = random.Random(seed)
    next_tick = time.perf_counter()
    while time.perf_counter() < stop_at:
        if interval:
            next_tick += interval
            delay = next_tick - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
        endpoint, method, path, extra = build_request(rng)
        started = time.perf_counter()
        try:
            response = await client.request(method, path, timeout=timeout, **extra)  # type: ignore[arg-type]
            stats.add(Sample(endpoint, response.status_code, time.perf_counter() - started))
        except httpx.HTTPError as error:
            stats.add(Sample(endpoint, 0, time.perf_counter() - started, type(error).__name__))


def summarize(stats: Stats, elapsed: float) -> dict[str, object]:
    samples = stats.samples
    total = len(samples)
    codes = Counter(s.status for s in samples)
    limited = codes.get(429, 0)
    server_errors = sum(n for code, n in codes.items() if code >= 500)
    transport = codes.get(0, 0)
    latencies = [s.seconds * 1000 for s in samples if s.status not in (0, 429)]
    per_endpoint: dict[str, dict[str, float]] = {}
    for name in sorted({s.endpoint for s in samples}):
        rows = [s for s in samples if s.endpoint == name]
        ok_ms = [s.seconds * 1000 for s in rows if s.status not in (0, 429)]
        per_endpoint[name] = {
            "requests": len(rows),
            "p50_ms": round(percentile(ok_ms, 50), 1),
            "p95_ms": round(percentile(ok_ms, 95), 1),
            "p99_ms": round(percentile(ok_ms, 99), 1),
        }
    return {
        "requests": total,
        "duration_s": round(elapsed, 2),
        "throughput_rps": round(total / elapsed, 1) if elapsed else 0.0,
        "status": {str(code or "transport_error"): n for code, n in sorted(codes.items())},
        "rate_limited_pct": round(100 * limited / total, 2) if total else 0.0,
        "error_pct": round(100 * (server_errors + transport) / total, 2) if total else 0.0,
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 1),
            "p95": round(percentile(latencies, 95), 1),
            "p99": round(percentile(latencies, 99), 1),
            "max": round(max(latencies, default=0.0), 1),
        },
        "per_endpoint": per_endpoint,
        "transport_errors": dict(Counter(s.error for s in samples if s.error)),
    }


def print_report(result: dict[str, object], args: argparse.Namespace) -> None:
    latency: dict[str, float] = result["latency_ms"]  # type: ignore[assignment]
    print(f"\n== Carga em {args.base}: {args.concurrency} conexões, {args.duration}s")
    print(f"requisições      {result['requests']}  ({result['throughput_rps']} req/s)")
    print(f"status           {result['status']}")
    print(f"429 (limitadas)  {result['rate_limited_pct']}%")
    print(f"erros (5xx/rede) {result['error_pct']}%")
    print(
        "latência (ms)    "
        f"p50={latency['p50']}  p95={latency['p95']}  p99={latency['p99']}  max={latency['max']}"
    )
    print("por endpoint:")
    per_endpoint: dict[str, dict[str, float]] = result["per_endpoint"]  # type: ignore[assignment]
    for name, row in per_endpoint.items():
        print(
            f"  {name:<16} n={int(row['requests']):<6} p50={row['p50_ms']:<8} "
            f"p95={row['p95_ms']:<8} p99={row['p99_ms']}"
        )


async def restock(client: httpx.AsyncClient, available: int) -> None:
    for slug in SEED_PRODUCTS:
        await client.put(f"/api/inventory/stock/{product_id(slug)}", json={"available": available})


async def run(args: argparse.Namespace) -> dict[str, object]:
    stats = Stats()
    limits = httpx.Limits(max_connections=args.concurrency + 10)
    interval = args.concurrency / args.rps if args.rps else 0.0
    async with httpx.AsyncClient(base_url=args.base, limits=limits) as client:
        if args.restock:
            await restock(client, args.restock)
        started = time.perf_counter()
        stop_at = started + args.duration
        await asyncio.gather(
            *(
                worker(client, stats, stop_at, interval, args.seed + i, args.timeout)
                for i in range(args.concurrency)
            )
        )
        elapsed = time.perf_counter() - started
    return summarize(stats, elapsed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--duration", type=float, default=20.0, help="segundos")
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--rps", type=float, default=0.0, help="taxa alvo total (0 = o máximo possível)")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--restock", type=int, default=100000, help="repõe o estoque antes (0 desliga)"
    )
    parser.add_argument("--json", help="grava o resultado completo neste arquivo")
    parser.add_argument("--max-error-rate", type=float, default=1.0, help="percentual aceito")
    args = parser.parse_args()

    result = asyncio.run(run(args))
    print_report(result, args)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"config": vars(args), "result": result}, handle, indent=2, ensure_ascii=False)
    error_pct: float = result["error_pct"]  # type: ignore[assignment]
    return 1 if error_pct > args.max_error_rate else 0


if __name__ == "__main__":
    sys.exit(main())
