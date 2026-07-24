import { useEffect, useRef, useState, type ReactNode } from "react";
import { motion, animate, useReducedMotion } from "framer-motion";

export const EASE = [0.2, 0, 0, 1] as const;

/* Enter-only page reveal: fade + 8px rise, 320ms, brand easing. */
export function PageTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: EASE }}
      className="h-full"
    >
      {children}
    </motion.div>
  );
}

export const staggerContainer = {
  animate: { transition: { staggerChildren: 0.03 } },
};

export const staggerItem = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.2, ease: EASE } },
};

/* Animated numeric counter (KPI cards). Snaps instantly under reduced motion. */
export function useCountUp(value: number | undefined): number {
  const target = value ?? 0;
  const reduced = useReducedMotion();
  const [display, setDisplay] = useState(0);
  const prev = useRef(0);

  useEffect(() => {
    if (reduced) {
      prev.current = target;
      setDisplay(target);
      return;
    }
    const controls = animate(prev.current, target, {
      duration: 0.6,
      ease: EASE,
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    prev.current = target;
    return () => controls.stop();
  }, [target, reduced]);

  return display;
}
