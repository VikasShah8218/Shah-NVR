import { useEffect, useState } from "react"
import { useSiteTime } from "@/api/queries"
import { DAY_MIN, siteWall, WEEK_MIN } from "@/lib/schedule"

/** The site clock schedules run on (SITE_TIMEZONE): fetched once a minute, moved forward locally in between. */
export function useSiteNow() {
  const site = useSiteTime()
  const [clock, setClock] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setClock(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  if (!site.data) return { zone: undefined, now: undefined }
  const w = siteWall(site.data.now)
  const passed = Math.max(0, Math.floor((clock - site.dataUpdatedAt) / 60_000))
  const total = (w.day * DAY_MIN + w.minute + passed) % WEEK_MIN
  return { zone: site.data.timezone, now: { day: Math.floor(total / DAY_MIN), minute: total % DAY_MIN } }
}
