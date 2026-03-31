import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div>
        <h1>OpenLoop</h1>
        <p>App shell placeholder</p>
      </div>
    </QueryClientProvider>
  )
}

export default App
