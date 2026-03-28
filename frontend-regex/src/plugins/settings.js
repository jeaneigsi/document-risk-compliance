const API_BASE_URL =
  localStorage.getItem('apiUrl') ||
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000/api/v1'

export const settings = {
  apiBaseUrl: API_BASE_URL,
}

export default settings
