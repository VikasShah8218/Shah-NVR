import { Camera as CameraIcon, Folder, KeyRound, Loader2, Save, ShieldCheck, User, Users, X } from "lucide-react"
import { useState } from "react"
import { useAccessGrants, useAccessSubjects, useAccessSummary, usePutGrants } from "@/api/queries"
import type { AccessGrants } from "@/api/types"
import { CameraPicker } from "@/components/CameraPicker"
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/common"
import { GroupPicker } from "@/components/GroupPicker"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { summaryText } from "@/lib/auth/permissions"
import { cn } from "@/lib/utils"

/** Which cameras each role / user may see (docs/AUTH_INTEGRATION_PLAN.md §6). What they may *do* comes from their
 *  role's permission numbers on the Auth Server; this page only decides *which cameras*. */

type Subject = { type: "role" | "user"; name: string; label: string }
type Item = { id: number; name: string }

const ADMIN_ROLE = "Admin"

export function AccessPage() {
  const subjects = useAccessSubjects()
  const summary = useAccessSummary()
  const [selected, setSelected] = useState<Subject | null>(null)
  const summaryOf = (type: string, name: string) => summary.data?.find((s) => s.subject_type === type && s.subject === name)

  const roles = subjects.data?.roles ?? []
  const users = subjects.data?.users ?? []

  return (
    <div>
      <PageHeader
        title="Access"
        description="Which cameras each role and user may see. What they may do (live, playback, export…) comes from their role on the Auth Server."
      />
      {(subjects.isLoading || summary.isLoading) && <Loading />}
      {subjects.error && <ErrorState error={subjects.error} />}
      {subjects.data && (
        <div className="grid gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <Card className="gap-0 py-2">
            <SectionTitle icon={Users} label="Roles" />
            {roles.length === 0 && <p className="px-4 pb-2 text-sm text-muted-foreground">No roles yet.</p>}
            {roles.map((role) => (
              <SubjectRow key={`r-${role}`} active={selected?.type === "role" && selected.name === role}
                icon={ShieldCheck} title={role} hint={summaryText(summaryOf("role", role), role === ADMIN_ROLE)}
                onClick={() => setSelected({ type: "role", name: role, label: role })} />
            ))}
            <SectionTitle icon={User} label="Users" />
            {users.length === 0 && <p className="px-4 pb-2 text-sm text-muted-foreground">No users have access to this application yet.</p>}
            {users.map((u) => (
              <SubjectRow key={`u-${u.id}`} active={selected?.type === "user" && selected.name === String(u.id)}
                icon={User} title={u.display_name} sub={`${u.username} · ${u.roles.join(", ") || "no role"}${u.is_active ? "" : " · inactive"}`}
                hint={summaryText(summaryOf("user", String(u.id)), false)}
                onClick={() => setSelected({ type: "user", name: String(u.id), label: `${u.display_name} (${u.username})` })} />
            ))}
          </Card>
          <div className="min-w-0">
            {selected ? (
              <GrantEditor key={`${selected.type}:${selected.name}`} subject={selected}
                isAdminRole={selected.type === "role" && selected.name === ADMIN_ROLE}
                userRoles={selected.type === "user" ? users.find((u) => String(u.id) === selected.name)?.roles ?? [] : []} />
            ) : (
              <EmptyState icon={KeyRound} title="Choose a role or a user">
                A user sees the cameras of their own grants plus those of each of their roles. Admins see everything.
              </EmptyState>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SectionTitle({ icon: Icon, label }: { icon: typeof Users; label: string }) {
  return (
    <div className="flex items-center gap-2 px-4 pt-3 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
      <Icon className="size-3.5" /> {label}
    </div>
  )
}

function SubjectRow({ active, icon: Icon, title, sub, hint, onClick }: {
  active: boolean
  icon: typeof Users
  title: string
  sub?: string
  hint: string
  onClick: () => void
}) {
  return (
    <button type="button" onClick={onClick}
      className={cn("mx-2 flex w-[calc(100%-1rem)] items-start gap-2.5 rounded-md px-2.5 py-2 text-left hover:bg-accent", active && "bg-accent")}>
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{title}</span>
        {sub && <span className="block truncate text-xs text-muted-foreground">{sub}</span>}
        <span className="block truncate text-xs text-muted-foreground">{hint}</span>
      </span>
    </button>
  )
}

function GrantEditor({ subject, isAdminRole, userRoles }: { subject: Subject; isAdminRole: boolean; userRoles: string[] }) {
  const grants = useAccessGrants({ type: subject.type, name: subject.name })
  if (grants.isLoading) return <Loading />
  if (grants.error) return <ErrorState error={grants.error} />
  if (!grants.data) return null
  // a fresh form for every load (also after Save), so it starts from what the server has
  return <GrantForm key={grants.dataUpdatedAt} subject={subject} initial={grants.data} isAdminRole={isAdminRole} userRoles={userRoles} />
}

function GrantForm({ subject, initial, isAdminRole, userRoles }: {
  subject: Subject
  initial: AccessGrants
  isAdminRole: boolean
  userRoles: string[]
}) {
  const save = usePutGrants()
  const [all, setAll] = useState(initial.all_cameras)
  const [groups, setGroups] = useState<Item[]>(initial.groups)
  const [cameras, setCameras] = useState<Item[]>(initial.cameras)
  const dirty = JSON.stringify([all, groups, cameras]) !== JSON.stringify([initial.all_cameras, initial.groups, initial.cameras])
  const add = (list: Item[], item: Item) => (list.some((x) => x.id === item.id) ? list : [...list, item].sort((a, b) => a.name.localeCompare(b.name)))

  return (
    <Card className="gap-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground uppercase">{subject.type === "role" ? "Role" : "User"}</div>
          <h2 className="truncate text-lg font-semibold">{subject.label}</h2>
          {subject.type === "user" && userRoles.length > 0 && (
            <p className="text-sm text-muted-foreground">Also sees the cameras of: {userRoles.map((r) => <Badge key={r} variant="secondary" className="mr-1">{r}</Badge>)}</p>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" disabled={!dirty || save.isPending}
            onClick={() => { setAll(initial.all_cameras); setGroups(initial.groups); setCameras(initial.cameras) }}>
            Reset
          </Button>
          <Button disabled={!dirty || save.isPending}
            onClick={() => save.mutate({ subject_type: subject.type, subject: subject.name, all_cameras: all,
              group_ids: groups.map((g) => g.id), camera_ids: cameras.map((c) => c.id) })}>
            {save.isPending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Save
          </Button>
        </div>
      </div>
      {isAdminRole && (
        <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
          The Admin role has every permission (<code>*</code>) and always sees every camera. Grants below are not needed.
        </p>
      )}

      <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2.5">
        <span>
          <span className="block text-sm font-medium">All cameras</span>
          <span className="block text-xs text-muted-foreground">Every camera, including ones added later.</span>
        </span>
        <Switch checked={all} onCheckedChange={setAll} />
      </label>

      <section className={cn("space-y-2", all && "pointer-events-none opacity-50")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium">Camera groups</h3>
            <p className="text-xs text-muted-foreground">A group includes all of its sub-groups.</p>
          </div>
          <GroupPicker className="w-64" value={null} placeholder="Add a group…"
            onChange={(id, g) => id != null && setGroups((list) => add(list, { id, name: g?.path_label ?? `Group #${id}` }))} />
        </div>
        <ItemList items={groups} icon={Folder} empty="No groups" onRemove={(id) => setGroups((l) => l.filter((x) => x.id !== id))} />
      </section>

      <section className={cn("space-y-2", all && "pointer-events-none opacity-50")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-medium">Single cameras</h3>
            <p className="text-xs text-muted-foreground">Cameras outside the chosen groups.</p>
          </div>
          <CameraPicker className="w-64" value={null} label="Add a camera…"
            onChange={(c) => setCameras((list) => add(list, { id: c.id, name: c.name }))} />
        </div>
        <ItemList items={cameras} icon={CameraIcon} empty="No single cameras" onRemove={(id) => setCameras((l) => l.filter((x) => x.id !== id))} />
      </section>
    </Card>
  )
}

function ItemList({ items, icon: Icon, empty, onRemove }: { items: Item[]; icon: typeof Folder; empty: string; onRemove: (id: number) => void }) {
  if (items.length === 0) return <p className="rounded-md border border-dashed px-3 py-3 text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="divide-y rounded-md border">
      {items.map((item) => (
        <li key={item.id} className="flex items-center gap-2 px-3 py-2 text-sm">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{item.name}</span>
          <Button variant="ghost" size="icon-sm" aria-label={`Remove ${item.name}`} onClick={() => onRemove(item.id)}><X /></Button>
        </li>
      ))}
    </ul>
  )
}
