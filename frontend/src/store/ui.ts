import { create } from "zustand";

interface UiState {
  cartOpen: boolean;
  paletteOpen: boolean;
  assistantOpen: boolean;
  setCartOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
  setAssistantOpen: (open: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  cartOpen: false,
  paletteOpen: false,
  assistantOpen: false,
  setCartOpen: (cartOpen) => set({ cartOpen }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setAssistantOpen: (assistantOpen) => set({ assistantOpen }),
}));
