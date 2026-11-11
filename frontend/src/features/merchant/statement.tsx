import { Check, Copy, Download } from "lucide-react";
import { m } from "motion/react";
import { Fragment, useMemo, useState } from "react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/misc";
import { useMerchantLedger } from "@/hooks/merchant";
import { formatMoney } from "@/lib/format";
import {
  type EntryTypeFilter,
  entriesToCsv,
  filterEntries,
  groupByDay,
  withRunningBalance,
} from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { useMerchant } from "./context";
import { Card, Segmented, TableSkeleton } from "./ui";

const TYPES: EntryTypeFilter[] = ["ALL", "CREDIT", "DEBIT"];
const TYPE_LABEL: Record<EntryTypeFilter, string> = {
  ALL: "Tudo",
  CREDIT: "Créditos",
  DEBIT: "Débitos",
};
const STEP = 30;

const dayLabel = new Intl.DateTimeFormat("pt-BR", {
  weekday: "long",
  day: "2-digit",
  month: "long",
});

function moneyText(cents: number) {
  return (cents / 100).toFixed(2).replace(".", ",");
}

function CopyAmount({ cents }: { cents: number }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(moneyText(cents));
          setDone(true);
          setTimeout(() => setDone(false), 1600);
          void toast.success("Valor copiado", { description: `R$ ${moneyText(cents)}` });
        } catch {
          void toast.error("Não foi possível copiar o valor");
        }
      }}
      aria-label={`Copiar valor ${formatMoney(cents)}`}
      className="grid size-9 place-items-center rounded-full text-muted transition-colors hover:bg-primary-soft hover:text-primary"
    >
      {done ? (
        <Check className="size-4 text-pix-ink" aria-hidden />
      ) : (
        <Copy className="size-4" aria-hidden />
      )}
    </button>
  );
}

export function Statement() {
  const { merchantId, merchantName, days } = useMerchant();
  const query = useMerchantLedger(merchantId);
  const [type, setType] = useState<EntryTypeFilter>("ALL");
  const [shown, setShown] = useState(STEP);

  const all = useMemo(() => withRunningBalance(query.data?.items ?? []), [query.data]);
  const since = Date.now() - days * 86_400_000;
  const inPeriod = useMemo(
    () => all.filter((r) => new Date(r.entry.created_at).getTime() >= since),
    [all, since],
  );
  const rows = useMemo(
    () => inPeriod.filter((r) => filterEntries([r.entry], type).length > 0),
    [inPeriod, type],
  );
  const groups = useMemo(() => groupByDay(rows.slice(0, shown)), [rows, shown]);
  const credits = inPeriod.reduce(
    (n, r) => n + (r.entry.direction === "CREDIT" ? r.entry.amount_cents : 0),
    0,
  );
  const debits = inPeriod.reduce(
    (n, r) => n + (r.entry.direction === "DEBIT" ? r.entry.amount_cents : 0),
    0,
  );
  const truncated = query.data ? query.data.total > query.data.items.length : false;

  const exportCsv = () => {
    const blob = new Blob([entriesToCsv(rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `extrato-${merchantName.toLowerCase().replace(/\s+/g, "-")}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    void toast.success("Extrato exportado", { description: `${rows.length} lançamentos em CSV.` });
  };

  return (
    <Card aria-labelledby="extrato">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="extrato" className="font-display text-xl font-semibold">
            Extrato
          </h2>
          <p className="mt-1 text-sm text-muted">
            Lançamentos do livro-razão, do mais recente para o mais antigo.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={exportCsv} disabled={rows.length === 0}>
          <Download aria-hidden /> Exportar CSV
        </Button>
      </div>

      <dl className="tabular mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl bg-pix-soft p-4">
          <dt className="text-sm text-pix-ink">Créditos no período</dt>
          <dd className="mt-1 font-display text-xl font-bold text-pix-ink">
            +{formatMoney(credits)}
          </dd>
        </div>
        <div className="rounded-2xl bg-surface-2 p-4">
          <dt className="text-sm text-muted">Débitos no período</dt>
          <dd className="mt-1 font-display text-xl font-bold">
            {debits > 0 ? "-" : ""}
            {formatMoney(debits)}
          </dd>
        </div>
        <div className="rounded-2xl bg-primary-soft p-4">
          <dt className="text-sm text-primary">Resultado do período</dt>
          <dd className="mt-1 font-display text-xl font-bold">{formatMoney(credits - debits)}</dd>
        </div>
      </dl>

      <div className="mt-5">
        <Segmented
          id="statement-type-pill"
          label="Filtrar por tipo"
          options={TYPES}
          value={type}
          onChange={(v) => {
            setType(v);
            setShown(STEP);
          }}
          render={(t) => TYPE_LABEL[t]}
        />
      </div>

      <div className="mt-5">
        {query.isError ? (
          <ErrorState
            error={query.error}
            onRetry={() => query.refetch()}
            title="Não foi possível carregar o extrato"
          />
        ) : query.isPending ? (
          <TableSkeleton rows={7} />
        ) : rows.length === 0 ? (
          <EmptyState
            art="pix"
            title="Nenhum lançamento"
            description={
              inPeriod.length === 0
                ? "Não há lançamentos neste período. Amplie o período para ver mais."
                : "Não há lançamentos deste tipo no período."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <caption className="sr-only">
                Lançamentos da conta do lojista agrupados por dia
              </caption>
              <thead className="text-xs tracking-wide text-muted uppercase">
                <tr className="border-b border-border">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Descrição
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 font-medium sm:table-cell">
                    Tipo
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right font-medium">
                    Valor
                  </th>
                  <th scope="col" className="w-10 py-2">
                    <span className="sr-only">Copiar</span>
                  </th>
                  <th scope="col" className="hidden py-2 pl-2 text-right font-medium md:table-cell">
                    Saldo acumulado
                  </th>
                </tr>
              </thead>
              {groups.map((g) => (
                <Fragment key={g.day}>
                  <tbody>
                    <tr>
                      <th
                        scope="rowgroup"
                        colSpan={3}
                        className="pt-5 pb-2 text-left text-sm font-semibold first-letter:uppercase"
                      >
                        {dayLabel.format(new Date(`${g.day}T12:00:00`))}
                      </th>
                      <td
                        colSpan={2}
                        className={cn(
                          "tabular pt-5 pb-2 text-right text-xs",
                          g.net >= 0 ? "text-pix-ink" : "text-danger",
                        )}
                      >
                        {g.net >= 0 ? "+" : "-"}
                        {formatMoney(Math.abs(g.net))} no dia
                      </td>
                    </tr>
                    {g.rows.map(({ entry: e, balance }, i) => (
                      <m.tr
                        key={e.id}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4, delay: Math.min(i, 8) * 0.03, ease: EASE }}
                        className="border-b border-border/60 transition-colors last:border-0 hover:bg-primary-soft/40"
                      >
                        <td className="py-2.5 pr-4">
                          <span className="block max-w-[22rem] truncate">{e.description}</span>
                          <span className="block text-xs text-muted sm:hidden">
                            {e.direction === "CREDIT" ? "Crédito" : "Débito"}
                          </span>
                        </td>
                        <td className="hidden py-2.5 pr-4 sm:table-cell">
                          <Badge tone={e.direction === "CREDIT" ? "pix" : "neutral"}>
                            {e.direction === "CREDIT" ? "Crédito" : "Débito"}
                          </Badge>
                        </td>
                        <td
                          className={cn(
                            "tabular py-2.5 pr-2 text-right font-semibold whitespace-nowrap",
                            e.direction === "CREDIT" && "text-pix-ink",
                          )}
                        >
                          {e.direction === "CREDIT" ? "+" : "-"}
                          {formatMoney(e.amount_cents)}
                        </td>
                        <td className="py-1">
                          <CopyAmount cents={e.amount_cents} />
                        </td>
                        <td className="tabular hidden py-2.5 pl-2 text-right whitespace-nowrap text-muted md:table-cell">
                          {formatMoney(balance)}
                        </td>
                      </m.tr>
                    ))}
                  </tbody>
                </Fragment>
              ))}
            </table>
          </div>
        )}
      </div>

      {rows.length > shown && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" onClick={() => setShown((n) => n + STEP)}>
            Mostrar mais ({rows.length - shown} restantes)
          </Button>
        </div>
      )}
      {truncated && query.data && (
        <p className="mt-4 text-center text-xs text-muted">
          O saldo acumulado considera os {query.data.items.length} lançamentos mais recentes de{" "}
          {query.data.total}.
        </p>
      )}
    </Card>
  );
}
