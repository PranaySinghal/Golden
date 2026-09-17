import { UploadPage } from './features/upload/UploadPage'

export default function App() {
  return (
    <div className="app">
      <header className="masthead">
        <h1 className="masthead__title">TidyLab</h1>
        <p className="masthead__tagline">Tidy your data. See what it was hiding.</p>
      </header>
      <main className="page">
        <UploadPage />
      </main>
    </div>
  )
}
