"use client";

import {
  useCart as useCartBase,
  type CartItem,
} from "@/app/context/CartContext";

/* =========================================================
   COMPATIBILITY WRAPPER
   (No logic changes, naming alignment only)
========================================================= */

export function useCart() {
  const cart = useCartBase();

  return {
    ...cart,

    // ✅ Alias for page expectation
    removeItem: cart.removeFromCart,
  };
}

export type { CartItem };
