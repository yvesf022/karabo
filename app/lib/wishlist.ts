"use client";

import { useState } from "react";

/* =========================================================
   WISHLIST – ID-BASED (PAGE CONTRACT)
========================================================= */

export function useWishlist() {
  const [wishlist, setWishlist] = useState<string[]>([]);

  const addToWishlist = (productId: string) => {
    setWishlist(prev =>
      prev.includes(productId) ? prev : [...prev, productId]
    );
  };

  const removeFromWishlist = (productId: string) => {
    setWishlist(prev => prev.filter(id => id !== productId));
  };

  return {
    wishlist,
    addToWishlist,
    removeFromWishlist,
  };
}
