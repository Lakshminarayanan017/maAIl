import { AnimatePresence, motion } from "framer-motion";
import { WifiOff } from "lucide-react";

import { useOnlineStatus } from "@/hooks/useOnlineStatus";
import { transitionFast } from "@/lib/motion";

/**
 * Clear offline state (08-ui-spec.md §4).
 *
 * It says what still works, because the honest answer for a mail client is
 * "what you have already synced". Claiming nothing works would be wrong, and
 * saying nothing at all would leave stale mail looking live.
 */
export function OfflineBanner() {
  const online = useOnlineStatus();

  return (
    <AnimatePresence>
      {online ? null : (
        <motion.div
          key="offline"
          role="status"
          aria-live="polite"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={transitionFast}
          className="overflow-hidden border-b border-warning-border bg-warning text-warning-fg"
        >
          <div className="flex items-center justify-center gap-2 px-s2 py-1.5 text-sm">
            <WifiOff className="size-3.5 shrink-0" aria-hidden />
            <span>You are offline. Mail already synced stays readable; nothing will send.</span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
