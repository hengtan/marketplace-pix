import { Check, Clock, Copy, FlaskConical, QrCode } from "lucide-react";
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

export function PixPanel({ pixCode, amountCents, expiresAt, onSimulate, simulating, onExpired }: Props) {
  const { remainingMs, expired } = useCountdown(expiresAt);
  const { copied, copy } = useCopy();
  const urgent = remainingMs > 0 && remainingMs < 60_000;
  const progress = Math.min(1, remainingMs / TOTAL_WINDOW_MS);

  useEffect(() => {
    if (expired) onExpired?.();
  }, [expired, onExpired]);

  return (
    <section
      aria-labelledby="pix-title"
      className="relative overflow-hidden rounded-xl border border-border bg-surface p-6 shadow-lift sm:p-8"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="pix-title" className="font-display text-2xl font-semibold">
            Pague com PIX
          </h2>
          <p className="mt-1 text-muted">Abra o app do seu banco e leia o QR Code ou cole o código.</p>
        </div>
        <div className="tabular text-right">
          <p className="text-sm text-muted">Valor</p>
          <p className="font-display text-3xl font-bold" data-testid="pix-amount">
            {formatMoney(amountCents)}
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-6 sm:grid-cols-[auto_1fr] sm:items-center">
        <div
          className={cn(
            "mx-auto rounded-lg bg-white p-4 shadow-soft transition-opacity",
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
        </div>

        <div className="grid gap-4">
          <div>
            <p id="pix-code-label" className="text-sm font-medium">
              PIX copia e cola
            </p>
            <p
              aria-labelledby="pix-code-label"
              className="mt-1.5 line-clamp-3 rounded-md bg-surface-2 p-3 font-mono text-xs leading-relaxed break-all text-muted"
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

          <div>
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-1.5 text-muted">
                <Clock className="size-4" aria-hidden /> {expired ? "PIX expirado" : "Expira em"}
              </span>
              <span
                className={cn("tabular font-mono text-lg font-semibold", urgent && "text-danger")}
                role="timer"
                aria-label={expired ? "PIX expirado" : `Tempo restante ${formatCountdown(remainingMs)}`}
                data-testid="countdown"
              >
                {formatCountdown(remainingMs)}
              </span>
            </div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
              <div
                className={cn(
                  "h-full origin-left rounded-full transition-transform duration-300 ease-linear",
                  urgent ? "bg-danger" : "bg-pix",
                )}
                style={{ transform: `scaleX(${progress})` }}
              />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3 rounded-lg bg-primary-soft px-4 py-3 text-sm text-primary">
        <QrCode className="size-4 shrink-0" aria-hidden />
        <span role="status">
          {expired ? "O tempo acabou. Estamos atualizando o pedido." : "Aguardando o pagamento. Esta tela atualiza sozinha."}
        </span>
      </div>

      {onSimulate && (
        <div className="mt-4 border-t border-dashed border-border pt-4">
          <Button variant="outline" onClick={onSimulate} disabled={simulating || expired} data-testid="simulate-pay">
            <FlaskConical /> {simulating ? "Simulando..." : "Simular pagamento"}
          </Button>
          <p className="mt-2 text-xs text-muted">Ferramenta de desenvolvimento. Não aparece em produção.</p>
        </div>
      )}
    </section>
  );
}
