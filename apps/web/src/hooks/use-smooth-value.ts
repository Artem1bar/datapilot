import { useMotionValue, useSpring, type SpringOptions } from "framer-motion";
import { useEffect } from "react";

const defaultSpring: SpringOptions = { stiffness: 200, damping: 25 };

/**
 * Returns a spring-animated MotionValue that smoothly transitions to
 * the target number. Ideal for progress bars & numeric counters.
 */
export function useSmoothValue(target: number, springConfig: SpringOptions = defaultSpring) {
  const motionValue = useMotionValue(target);
  const springValue = useSpring(motionValue, springConfig);

  useEffect(() => {
    motionValue.set(target);
  }, [target, motionValue]);

  return springValue;
}
