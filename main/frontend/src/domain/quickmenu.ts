import type { QuickmenuItem } from './types'

export function quickmenuDisplayLabel(it: QuickmenuItem | null | undefined): string {
  if (!it || typeof it !== 'object') return ''
  const d = String(it.quickmenu_display_label || '').trim()
  if (d) return d
  for (const k of ['quickmenu_label', 'subcategory', 'category', 'domain'] as const) {
    const v = String(it[k] || '').trim()
    if (v && v !== '-') return v
  }
  return String(it.qna_code || '').trim()
}
