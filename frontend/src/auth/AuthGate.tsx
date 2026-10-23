import type { ReactNode } from "react";
import { Center, Loader } from "@mantine/core";
import { Navigate, useLocation } from "react-router-dom";
import { useMe } from "@/api/hooks";
import { locale, setLocale } from "@/lib/i18n";

export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isLoading) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError || !me.data) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (me.data.locale && me.data.locale !== locale()) {
    setLocale(me.data.locale);  // the language saved with the user wins (reloads once)
    return null;
  }
  return <>{children}</>;
}
