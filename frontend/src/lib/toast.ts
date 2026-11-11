type ToastOptions = { description?: string; [key: string]: unknown };

let release: () => void = () => {};
const mounted = new Promise<void>((resolve) => {
  release = resolve;
});

export function markToasterMounted() {
  release();
}

async function show(
  kind: "success" | "error" | "message",
  message: string,
  options?: ToastOptions,
) {
  const { toast } = await import("sonner");
  await mounted;
  toast[kind](message, options);
}

export const toast = {
  success: (message: string, options?: ToastOptions) => show("success", message, options),
  error: (message: string, options?: ToastOptions) => show("error", message, options),
  message: (message: string, options?: ToastOptions) => show("message", message, options),
  dismiss: () => {
    void import("sonner").then((m) => m.toast.dismiss());
  },
};
