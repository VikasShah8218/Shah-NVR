/** Event recording settings of a camera (docs/EVENT_RECORDING_PLAN.md E6). */
export type EventSettings = { pre: number; post: number; marking: boolean }
export const EVENT_DEFAULTS: EventSettings = { pre: 10, post: 30, marking: true }
export const eventSettingsValid = (e: EventSettings) =>
  Number.isInteger(e.pre) && e.pre >= 0 && e.pre <= 60 && Number.isInteger(e.post) && e.post >= 0 && e.post <= 600
