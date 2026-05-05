"use client";

import { motion } from "framer-motion";

// Next.js App Router re-mounts template.tsx on every route change, so the
// initial → animate cycle fires naturally on each navigation — no AnimatePresence
// wrapper needed.  This gives a consistent fade + slight-lift entrance for all pages.
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 60, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.9, ease: [0.25, 0.46, 0.45, 0.94] }}
      style={{ minHeight: "100%", width: "100%" }}
    >
      {children}
    </motion.div>
  );
}
