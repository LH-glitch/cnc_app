"use client";

import { usePathname } from "next/navigation";
import Nav from "./Nav";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/") return <>{children}</>;
  return (
    <div style={{ display: "flex", flexDirection: "row", minHeight: "100vh" }}>
      <Nav />
      <div className="page-content">{children}</div>
    </div>
  );
}
