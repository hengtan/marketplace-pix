import { create } from "zustand";

interface UiState {
  cartOpen: boolean;
  paletteOpen: boolean;
  setCartOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  cartOpen: false,
  paletteOpen: false,
  setCartOpen: (cartOpen) => set({ cartOpen }),
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
}));
