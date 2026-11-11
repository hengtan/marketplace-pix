import { create } from "zustand";

interface UiState {
  cartOpen: boolean;
  paletteOpen: boolean;
  assistantOpen: boolean;
  cartBump: number;
  lastSlug: string | null;
  setLastSlug: (slug: string | null) => void;
  setCartOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
  setAssistantOpen: (open: boolean) => void;
  bumpCart: () => void;
}

export const useUi = create<UiState>((set) => ({
  cartOpen: false,
  paletteOpen: false,
  assistantOpen: false,
  cartBump: 0,
  lastSlug: null,
  setLastSlug: (lastSlug) => set({ lastSlug }),
  setCartOpen: (cartOpen) => set({ cartOpen }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setAssistantOpen: (assistantOpen) => set({ assistantOpen }),
  bumpCart: () => set((s) => ({ cartBump: s.cartBump + 1 })),
}));
