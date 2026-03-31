const API_BASE = '/api/v1'

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`)
  return res.json()
}
