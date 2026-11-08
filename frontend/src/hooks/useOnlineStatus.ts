import { useEffect, useState } from "react";

/**
 * Drives the offline state the spec asks for (§4: "Clear empty, error and
 * offline states"). `navigator.onLine` only knows about the network interface,
 * so phase 2 adds a failed-request signal on top of it; the hook's shape does
 * not change when it does.
 */
export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
