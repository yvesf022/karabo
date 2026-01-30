// lib/store.ts

import { create } from "zustand";

type StoreState = {
  wishlist: string[];

  toggleWishlist: (productId: string) => void;
  isWishlisted: (productId: string) => boolean;
};

export const useStore = create<StoreState>((set, get) => ({
  wishlist: [],

  toggleWishlist: (productId) =>
    set((state) => ({
      wishlist: state.wishlist.includes(productId)
        ? state.wishlist.filter((id) => id !== productId)
        : [...state.wishlist, productId],
    })),

  isWishlisted: (productId) => get().wishlist.includes(productId),
}));
