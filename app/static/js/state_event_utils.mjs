export function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage errors (private mode / quota / disabled storage).
  }
}

export function removeStorage(key) {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Ignore storage errors (private mode / quota / disabled storage).
  }
}

export function readStorageBool(key, defaultValue = false) {
  const raw = readStorage(key);
  if (raw === null) {
    return defaultValue;
  }
  return raw === "1";
}
