import { ShieldX } from "lucide-react"
import type { ReactNode } from "react"
import { Navigate } from "react-router"
import { EmptyState } from "@/components/common"
import { NAV } from "@/components/layout/nav"
import { useAuth } from "./useAuth"

/** A page that needs one of `any` (the server refuses the API calls anyway; this avoids a page full of errors). */
export function RequirePerm({ any, children }: { any: readonly number[]; children: ReactNode }) {
  const { can } = useAuth()
  if (can(...any)) return <>{children}</>
  return (
    <EmptyState icon={ShieldX} title="No access">
      Your role does not allow this page. Ask an administrator if you need it.
    </EmptyState>
  )
}

/** The home page is the dashboard; users without it start on the first page they may open. */
export function HomeRoute({ children, perms }: { children: ReactNode; perms: readonly number[] }) {
  const { can } = useAuth()
  if (can(...perms)) return <>{children}</>
  const first = NAV.find((item) => item.to !== "/" && can(...item.perms))
  return <Navigate to={first?.to ?? "/settings"} replace />
}
