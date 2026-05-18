export enum EventContracts {
  CATALOG_CLICKED = "catalog:clicked",
  CATALOG_MORE_CLICKED = "catalog:more_clicked",
  CLOSE_CLICKED = "close:clicked",
}

export interface EventPayload<T = unknown> {
  source: string
  version: string
  event: EventContracts
  payload: T
  timestamp: string
}

function emit<T>(event: EventContracts, payload: T) {
  const message: EventPayload<T> = {
    source: "exmatch-chat",
    version: "1.0.0",
    event,
    payload,
    timestamp: new Date().toISOString(),
  }
  window.parent.postMessage(message, "*")
}

export function emitCatalogClicked(payload: { id: string; name: string; type: "company" | "product" }) {
  emit(EventContracts.CATALOG_CLICKED, payload)
}

export function emitCatalogMoreClicked() {
  emit(EventContracts.CATALOG_MORE_CLICKED, {})
}

export function emitCloseClicked() {
  emit(EventContracts.CLOSE_CLICKED, {})
}
