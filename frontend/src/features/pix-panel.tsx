import { Check, Clock, Copy, FlaskConical, QrCode } from "lucide-react";
import { m, useReducedMotion } from "motion/react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { useCopy, useCountdown } from "@/hooks/utils";
import { formatCountdown, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  pixCode: string;
  amountCents: number;
  expiresAt: string;
  onSimulate?: () => void;
  simulating?: boolean;
  onExpired?: () => void;
}

const TOTAL_WINDOW_MS = 10 * 60 * 1000;
const RING = 2 * Math.PI * 44;

export function PixPanel({
  pixCode,
  amountCents,
  expiresAt,
  onSimulate,
  simulating,
  onExpired,
}: Props) {
  const { remainingMs, expired } = useCountdown(expiresAt);
  const { copied, copy } = useCopy();
  const reduce = useReducedMotion();
  const urgent = remainingMs > 0 && remainingMs < 60_000;
  const progress = Math.min(1, remainingMs / TOTAL_WINDOW_MS);

  useEffect(() => {
    if (expired) onExpired?.();
  }, [expired, onExpired]);

  return (
    <section
      aria-labelledby="pix-title"
      className="panel hairline-top relative overflow-hidden rounded-3xl p-6 shadow-lift sm:p-8"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="pix-title" className="font-display text-2xl font-semibold">
            Pague com PIX
          </h2>
          <p className="mt-1 text-muted">
            Abra o app do seu banco e leia o QR Code ou cole o código.
          </p>
        </div>
        <div className="tabular shrink-0 text-right">
          <p className="text-sm text-muted">Valor</p>
          <p className="font-display text-3xl font-bold whitespace-nowrap" data-testid="pix-amount">
            {formatMoney(amountCents)}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-[auto_1fr] sm:items-center">
        <div
          className={cn(
            "relative mx-auto overflow-hidden rounded-3xl bg-white p-4 shadow-lift ring-1 ring-black/5 transition-opacity",
            expired && "opacity-25 grayscale",
          )}
        >
          <QRCodeSVG
            value={pixCode}
            size={208}
            level="M"
            marginSize={0}
            fgColor="#10163a"
            bgColor="#ffffff"
            role="img"
            aria-label="QR Code do PIX"
            title="QR Code do PIX"
          />
          {!expired && !reduce && (
            <m.span
              aria-hidden
              className="pointer-events-none absolute inset-x-3 top-0 h-10 bg-gradient-to-b from-transparent via-[oklch(0.74_0.175_165/0.45)] to-transparent"
              initial={{ y: -40 }}
              animate={{ y: [-40, 230, -40] }}
              transition={{ duration: 3.4, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
            />
          )}
        </div>

        <div className="grid gap-4">
          <div>
            <p id="pix-code-label" className="text-sm font-medium">
              PIX copia e cola
            </p>
            <p
              className="mt-1.5 max-h-28 overflow-y-auto rounded-md bg-surface-2 p-3 font-mono text-[0.7rem] leading-relaxed break-all text-muted"
              data-testid="pix-code"
            >
              {pixCode}
            </p>
          </div>

          <Button
            size="lg"
            variant={copied ? "pix" : "primary"}
            onClick={() => copy(pixCode)}
            disabled={expired}
            data-testid="copy-pix"
          >
            {copied ? <Check /> : <Copy />}
            {copied ? "Código copiado" : "Copiar código PIX"}
          </Button>
          <span role="status" className="sr-only">
            {copied ? "Código PIX copiado para a área de transferência" : ""}
          </span>

          <div className="flex items-center gap-4">
            <div className="relative grid size-24 shrink-0 place-items-center">
              <svg
                viewBox="0 0 100 100"
                className="absolute inset-0 size-full -rotate-90"
                aria-hidden
              >
                <circle
                  cx="50"
                  cy="50"
                  r="44"
                  fill="none"
                  strokeWidth="6"
                  className="stroke-surface-3"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="44"
                  fill="none"
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray={RING}
                  strokeDashoffset={RING * (1 - progress)}
                  className={cn(
                    "transition-[stroke-dashoffset] duration-300 ease-linear",
                    urgent ? "stroke-danger" : "stroke-pix",
                  )}
                />
              </svg>
              <span
                className={cn("tabular font-mono text-xl font-semibold", urgent && "text-danger")}
                role="timer"
                aria-label={
                  expired ? "PIX expirado" : `Tempo restante ${formatCountdown(remainingMs)}`
                }
                data-testid="countdown"
              >
                {formatCountdown(remainingMs)}
              </span>
            </div>
            <p className="flex items-center gap-1.5 text-sm text-muted">
              <Clock className="size-4" aria-hidden /> {expired ? "PIX expirado" : "Expira em"}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3 rounded-2xl bg-primary-soft px-4 py-3 text-sm text-primary">
        <QrCode className="size-4 shrink-0" aria-hidden />
        <span role="status">
          {expired
            ? "O tempo acabou. Estamos atualizando o pedido."
            : "Aguardando o pagamento. Esta tela atualiza sozinha."}
        </span>
      </div>

      {onSimulate && (
        <div className="mt-4 border-t border-dashed border-border pt-4">
          <Button
            variant="outline"
            onClick={onSimulate}
            disabled={simulating || expired}
            data-testid="simulate-pay"
          >
            <FlaskConical /> {simulating ? "Simulando..." : "Simular pagamento"}
          </Button>
          <p className="mt-2 text-xs text-muted">
            Ferramenta de desenvolvimento. Não aparece em produção.
          </p>
        </div>
      )}
    </section>
  );
}
