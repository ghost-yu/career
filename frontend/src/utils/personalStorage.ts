const OWNER_KEY = 'career_storage_owner'
let currentOwner = ''

export function setStorageOwner(userId: string) {
  currentOwner = userId
  window.localStorage.setItem(OWNER_KEY, userId)
}

export function personalStorageKey(base: string) {
  const owner = currentOwner || 'anonymous'
  return `${base}:${owner}`
}
