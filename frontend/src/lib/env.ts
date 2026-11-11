export const env = {
  apiUrl: (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000",
  useMocks: import.meta.env.VITE_USE_MOCKS === "true",
  devTools: import.meta.env.VITE_ENABLE_DEV_TOOLS === "true",
};
