import { BackendStatus } from './components/BackendStatus'

export default function App() {
  return (
    <main className="page">
      <h1>Golden Analytics</h1>
      <p className="lede">
        Clean up a spreadsheet and see how the cleanup changes the answers it gives you.
      </p>
      <BackendStatus />
      <p className="placeholder">File upload is coming next.</p>
    </main>
  )
}
