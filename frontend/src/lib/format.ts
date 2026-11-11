const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const dateFmt = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});
const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});
const shortDayFmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });

export function formatMoney(cents: number): string {
  return brl.format(cents / 100).replace(/ /g, " ");
}

export function formatDate(iso: string): string {
  return dateFmt.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTimeFmt.format(new Date(iso));
}

export function formatShortDay(iso: string): string {
  return shortDayFmt.format(new Date(`${iso}T12:00:00`));
}

export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function formatRating(rating: number): string {
  return rating.toFixed(1).replace(".", ",");
}

export function pluralize(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function shortId(id: string): string {
  return id.slice(0, 8).toUpperCase();
}
